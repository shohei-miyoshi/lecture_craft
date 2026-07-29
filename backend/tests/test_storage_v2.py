from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from pathlib import Path

from app.db import db_conn, init_db
from app.jobs import JobManager, JobRecord
from app.models import PreviewAudioRequest
from app.persistence import export_research_jsonl, save_project_events
from app.service import ApiError, ensure_preview_sentence_audio
from app.storage import get_artifact_store
from app.storage_persistence import (
    apply_generated_result,
    assert_final_render_context_current,
    confirm_review_stage,
    create_final_render_input_revision,
    create_generation_run_v2,
    create_project_v2,
    get_artifact_for_request,
    get_final_render_context,
    get_project_v2,
    get_review_assignment_context,
    list_projects_v2,
    publish_preview_audio_result,
    register_stored_file,
    save_project_draft,
    save_source_pdf,
    update_run_analysis_status,
)


class StorageV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        os.environ["DATABASE_URL"] = f"sqlite:///{root / 'app.db'}"
        os.environ["LECTURE_CRAFT_STORAGE_ROOT"] = str(root / "storage")
        init_db()
        now = "2026-07-27T00:00:00"
        with db_conn() as conn:
            for user_id in ("user_a", "user_b"):
                conn.execute(
                    """
                    INSERT INTO users (
                        id, user_kind, username, password_hash, role,
                        is_active, created_at, updated_at
                    ) VALUES (
                        :id, 'registered', :username, 'not-used', 'user',
                        1, :created_at, :updated_at
                    )
                    """,
                    {
                        "id": user_id,
                        "username": user_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _project_with_pdf(self):
        project = create_project_v2(
            user_id="user_a",
            experiment_id=None,
            name="保存テスト",
            usage_context="general",
        )
        uploaded = save_source_pdf(
            project_id=project["id"],
            user_id="user_a",
            stream=io.BytesIO(b"%PDF-1.4\nstorage-test\n%%EOF"),
            filename="slides.pdf",
            media_type="application/pdf",
        )
        return get_project_v2(project["id"], "user_a"), uploaded

    def _project_run_with_slide(self, mode: str):
        project, uploaded = self._project_with_pdf()
        run = create_generation_run_v2(
            project_id=project["id"],
            user_id="user_a",
            experiment_id=None,
            source_artifact_id=uploaded["artifact"]["id"],
            mode=mode,
            detail="standard",
            difficulty="basic",
            conditions={},
            usage_context="general",
        )
        slide_file = Path(self.temp_dir.name) / f"{mode}-slide.png"
        slide_file.write_bytes(b"test-slide")
        stored = get_artifact_store().put_file(
            slide_file,
            project_id=project["id"],
            run_id=run["id"],
            stage="layout/slides",
            original_filename="slide_001.png",
            media_type="image/png",
        )
        artifact = register_stored_file(
            stored,
            project_id=project["id"],
            user_id="user_a",
            artifact_kind="slide_image",
            stage="layout/slides",
            run_id=run["id"],
            metadata={"slide_idx": 0},
        )
        current = get_project_v2(project["id"], "user_a")
        saved = save_project_draft(
            project_id=project["id"],
            user_id="user_a",
            base_version=current["draft_version"],
            state={
                **current["data"],
                "mode": mode,
                "slides": [{
                    "id": "sl0",
                    "image_artifact_id": artifact["id"],
                    "image_url": artifact["content_url"],
                }],
                "sentences": [{
                    "id": "s1",
                    "slide_idx": 0,
                    "text": "確認済み台本",
                    "start_sec": 0,
                    "end_sec": 3,
                }],
                "highlights": [],
            },
        )
        return saved, run

    def test_pdf_is_restored_from_artifact_catalog(self) -> None:
        project, uploaded = self._project_with_pdf()
        self.assertTrue(project["data"]["input_pdf"]["available"])
        self.assertEqual(project["source_artifact"]["id"], uploaded["artifact"]["id"])
        artifact = get_artifact_for_request(
            uploaded["artifact"]["id"],
            requester_user_id="user_a",
            requester_role="user",
        )
        self.assertTrue(Path(artifact["path"]).exists())
        with self.assertRaises(ApiError) as denied:
            get_artifact_for_request(
                uploaded["artifact"]["id"],
                requester_user_id="user_b",
                requester_role="user",
            )
        self.assertEqual(denied.exception.status_code, 403)

    def test_plain_video_skips_layout_and_assignment_reviews(self) -> None:
        project, run = self._project_run_with_slide("video")
        script = confirm_review_stage(
            project_id=project["id"],
            user_id="user_a",
            run_id=run["id"],
            stage="script",
            draft_version=project["draft_version"],
        )
        review_states = get_project_v2(project["id"], "user_a")["review_states"]
        self.assertEqual(review_states["script"]["status"], "confirmed")
        self.assertNotIn("layout", review_states)
        with self.assertRaises(ApiError) as assignment:
            confirm_review_stage(
                project_id=project["id"],
                user_id="user_a",
                run_id=run["id"],
                stage="assignment",
                draft_version=script["revision"]["draft_version"],
            )
        self.assertEqual(assignment.exception.code, "ASSIGNMENT_NOT_REQUIRED")

        render_input = create_final_render_input_revision(
            project_id=project["id"],
            user_id="user_a",
            run_id=run["id"],
            draft_version=project["draft_version"],
        )
        context = get_final_render_context(
            project_id=project["id"],
            user_id="user_a",
            run_id=run["id"],
            render_type="video",
            input_revision_id=render_input["id"],
        )
        self.assertEqual(context["input_stage"], "render_input")
        self.assertEqual(context["state"]["sentences"][0]["text"], "確認済み台本")
        assert_final_render_context_current(context)

        latest = get_project_v2(project["id"], "user_a")
        save_project_draft(
            project_id=project["id"],
            user_id="user_a",
            base_version=latest["draft_version"],
            state={
                **latest["data"],
                "sentences": [{**latest["data"]["sentences"][0], "text": "生成中に変更"}],
            },
        )
        with self.assertRaises(ApiError) as stale:
            assert_final_render_context_current(context)
        self.assertEqual(stale.exception.code, "FINAL_RENDER_INPUT_BECAME_STALE")

    def test_audio_run_cannot_create_video_render(self) -> None:
        project, run = self._project_run_with_slide("audio")
        confirm_review_stage(
            project_id=project["id"],
            user_id="user_a",
            run_id=run["id"],
            stage="script",
            draft_version=project["draft_version"],
        )
        with self.assertRaises(ApiError) as render:
            create_final_render_input_revision(
                project_id=project["id"],
                user_id="user_a",
                run_id=run["id"],
                draft_version=project["draft_version"],
            )
        self.assertEqual(render.exception.code, "VIDEO_RENDER_NOT_AVAILABLE")

    def test_legacy_project_without_draft_remains_visible_and_loadable(self) -> None:
        now = "2026-07-27T00:00:00"
        state = {
            "mode": "hl",
            "slides": [{"id": "slide_1"}],
            "sentences": [{"id": "sentence_1", "text": "旧台本"}],
            "highlights": [{"id": "highlight_1"}],
            "input_pdf": {
                "name": "legacy.pdf",
                "type": "application/pdf",
                "size": 1234,
                "sha256": "legacy-sha256",
                "available": True,
            },
        }
        with db_conn() as conn:
            conn.execute(
                """
                INSERT INTO projects (
                    id, user_id, name, latest_state_json, generation_refs_json,
                    review_states_json, usage_context, analysis_status,
                    created_at, updated_at
                ) VALUES (
                    'legacy_project', 'user_a', '旧プロジェクト', :state_json,
                    '{}', '{}', 'general', 'excluded', :created_at, :updated_at
                )
                """,
                {
                    "state_json": json.dumps(state, ensure_ascii=False),
                    "created_at": now,
                    "updated_at": now,
                },
            )

        projects = list_projects_v2("user_a")
        legacy_summary = next(row for row in projects if row["id"] == "legacy_project")
        self.assertEqual(legacy_summary["slide_count"], 1)
        self.assertTrue(legacy_summary["has_pdf"])

        project = get_project_v2("legacy_project", "user_a")
        self.assertEqual(project["data"]["sentences"][0]["text"], "旧台本")
        self.assertEqual(project["data"]["input_pdf"]["download_url"], "/api/projects/legacy_project/pdf")

    def test_draft_uses_optimistic_lock(self) -> None:
        project, _ = self._project_with_pdf()
        saved = save_project_draft(
            project_id=project["id"],
            user_id="user_a",
            base_version=project["draft_version"],
            state={**project["data"], "sentences": [{"id": "s1", "slide_idx": 0, "text": "本文"}]},
        )
        self.assertGreater(saved["draft_version"], project["draft_version"])
        with self.assertRaises(ApiError) as conflict:
            save_project_draft(
                project_id=project["id"],
                user_id="user_a",
                base_version=project["draft_version"],
                state=project["data"],
            )
        self.assertEqual(conflict.exception.status_code, 409)

    def test_slide_artifact_refs_are_restored_when_client_drops_them(self) -> None:
        project, uploaded = self._project_with_pdf()
        run = create_generation_run_v2(
            project_id=project["id"],
            user_id="user_a",
            experiment_id=None,
            source_artifact_id=uploaded["artifact"]["id"],
            mode="hl",
            detail="standard",
            difficulty="basic",
            conditions={},
            usage_context="general",
        )
        slide_file = Path(self.temp_dir.name) / "slide.png"
        slide_file.write_bytes(b"test-slide")
        stored = get_artifact_store().put_file(
            slide_file,
            project_id=project["id"],
            run_id=run["id"],
            stage="layout/slides",
            original_filename="slide_001.png",
            media_type="image/png",
        )
        artifact = register_stored_file(
            stored,
            project_id=project["id"],
            user_id="user_a",
            artifact_kind="slide_image",
            stage="layout/slides",
            run_id=run["id"],
            metadata={"slide_idx": 0},
        )

        current = get_project_v2(project["id"], "user_a")
        damaged_state = {
            **current["data"],
            "slides": [{"id": "sl0", "image_available": True}],
        }
        with db_conn() as conn:
            conn.execute(
                """
                UPDATE project_drafts
                SET state_json = :state_json
                WHERE project_id = :project_id
                """,
                {
                    "state_json": json.dumps(damaged_state),
                    "project_id": project["id"],
                },
            )
        restored = get_project_v2(project["id"], "user_a")
        self.assertEqual(restored["data"]["slides"][0]["image_artifact_id"], artifact["id"])
        self.assertEqual(restored["data"]["slides"][0]["image_url"], artifact["content_url"])

        saved = save_project_draft(
            project_id=project["id"],
            user_id="user_a",
            base_version=current["draft_version"],
            state=damaged_state,
        )

        self.assertEqual(saved["data"]["slides"][0]["image_artifact_id"], artifact["id"])
        self.assertEqual(saved["data"]["slides"][0]["image_url"], artifact["content_url"])
        with db_conn() as conn:
            row = conn.execute(
                "SELECT state_json FROM project_drafts WHERE project_id = :project_id",
                {"project_id": project["id"]},
            ).fetchone()
        persisted = json.loads(row["state_json"])
        self.assertEqual(persisted["slides"][0]["image_artifact_id"], artifact["id"])
        self.assertEqual(persisted["slides"][0]["image_url"], artifact["content_url"])

    def test_job_lease_allows_only_one_worker(self) -> None:
        now = "2026-07-27T00:00:00"
        first = JobManager()
        second = JobManager()
        record = JobRecord(
            job_id="job_lease_test",
            kind="project_run",
            status="queued",
            progress=0,
            message="queued",
            created_at=now,
            updated_at=now,
            owner_user_id="user_a",
        )
        first.jobs[record.job_id] = record
        first._persist_job(record, strict=True)
        second.jobs[record.job_id] = JobRecord(**record.__dict__)

        self.assertTrue(first._claim_job(record.job_id))
        self.assertFalse(second._claim_job(record.job_id))
        with db_conn() as conn:
            row = conn.execute(
                "SELECT status, lease_owner FROM jobs WHERE id = :job_id",
                {"job_id": record.job_id},
            ).fetchone()
        self.assertEqual(row["status"], "running")
        self.assertEqual(row["lease_owner"], first.worker_instance_id)

    def test_replacing_pdf_invalidates_active_run(self) -> None:
        project, uploaded = self._project_with_pdf()
        run = create_generation_run_v2(
            project_id=project["id"],
            user_id="user_a",
            experiment_id=None,
            source_artifact_id=uploaded["artifact"]["id"],
            mode="hl",
            detail="standard",
            difficulty="basic",
            conditions={},
            usage_context="general",
        )
        replaced = save_source_pdf(
            project_id=project["id"],
            user_id="user_a",
            stream=io.BytesIO(b"%PDF-1.4\nreplacement\n%%EOF"),
            filename="replacement.pdf",
            media_type="application/pdf",
        )
        current = get_project_v2(project["id"], "user_a")
        self.assertIsNone(current["active_run_id"])
        self.assertEqual(current["source_artifact"]["id"], replaced["artifact"]["id"])
        self.assertEqual(current["data"]["slides"], [])
        self.assertEqual(current["data"]["sentences"], [])
        with db_conn() as conn:
            run_row = conn.execute(
                "SELECT status FROM generation_runs WHERE id = :run_id",
                {"run_id": run["id"]},
            ).fetchone()
        self.assertEqual(run_row["status"], "superseded")
        with self.assertRaises(ApiError) as stale:
            apply_generated_result(
                project_id=project["id"],
                user_id="user_a",
                run_id=run["id"],
                result={"slides": [], "sentences": [], "highlights": []},
            )
        self.assertEqual(stale.exception.code, "GENERATION_RUN_STALE")

    def test_starting_new_run_supersedes_previous_run(self) -> None:
        project, uploaded = self._project_with_pdf()
        first = create_generation_run_v2(
            project_id=project["id"],
            user_id="user_a",
            experiment_id=None,
            source_artifact_id=uploaded["artifact"]["id"],
            mode="hl",
            detail="standard",
            difficulty="basic",
            conditions={},
            usage_context="general",
        )
        second = create_generation_run_v2(
            project_id=project["id"],
            user_id="user_a",
            experiment_id=None,
            source_artifact_id=uploaded["artifact"]["id"],
            mode="hl",
            detail="detail",
            difficulty="advanced",
            conditions={},
            usage_context="research",
        )
        current = get_project_v2(project["id"], "user_a")
        self.assertEqual(current["active_run_id"], second["id"])
        with db_conn() as conn:
            first_row = conn.execute(
                "SELECT status FROM generation_runs WHERE id = :run_id",
                {"run_id": first["id"]},
            ).fetchone()
        self.assertEqual(first_row["status"], "superseded")

    def test_research_export_uses_included_runs_only(self) -> None:
        project, uploaded = self._project_with_pdf()
        run = create_generation_run_v2(
            project_id=project["id"],
            user_id="user_a",
            experiment_id=None,
            source_artifact_id=uploaded["artifact"]["id"],
            mode="hl",
            detail="standard",
            difficulty="basic",
            conditions={"kg_mode": "slide"},
            usage_context="research",
        )
        save_project_events(
            project_id=project["id"],
            user_id="user_a",
            events=[
                {
                    "external_event_id": "event-run-scope",
                    "generation_run_id": run["id"],
                    "action_type": "sentence_text_changed",
                    "entity_type": "sentence",
                    "entity_id": "s1",
                    "before": {"text": "before"},
                    "after": {"text": "after"},
                }
            ],
        )
        candidate_export = export_research_jsonl(
            actor_user_id="user_a",
            included_only=True,
        )
        self.assertEqual(candidate_export["row_count"], 0)

        update_run_analysis_status(run["id"], "included")
        included_export = export_research_jsonl(
            actor_user_id="user_a",
            included_only=True,
        )
        self.assertEqual(included_export["row_count"], 1)
        with db_conn() as conn:
            export_row = conn.execute(
                "SELECT output_path FROM research_export_snapshots WHERE id = :id",
                {"id": included_export["export_id"]},
            ).fetchone()
        jsonl = get_artifact_store().resolve(export_row["output_path"]).read_text(encoding="utf-8")
        self.assertIn('"run_hash"', jsonl)
        self.assertNotIn(run["id"], jsonl)
        self.assertNotIn("user_a", jsonl)

    def test_assignment_uses_confirmed_revisions_and_becomes_stale(self) -> None:
        project, uploaded = self._project_with_pdf()
        run = create_generation_run_v2(
            project_id=project["id"],
            user_id="user_a",
            experiment_id=None,
            source_artifact_id=uploaded["artifact"]["id"],
            mode="hl",
            detail="standard",
            difficulty="basic",
            conditions={},
            usage_context="research",
        )
        slide_file = Path(self.temp_dir.name) / "slide.png"
        slide_file.write_bytes(b"not-a-real-png")
        stored = get_artifact_store().put_file(
            slide_file,
            project_id=project["id"],
            run_id=run["id"],
            stage="layout/slides",
            original_filename="slide_001.png",
            media_type="image/png",
        )
        register_stored_file(
            stored,
            project_id=project["id"],
            user_id="user_a",
            artifact_kind="slide_image",
            stage="layout/slides",
            run_id=run["id"],
            metadata={"slide_idx": 0},
        )
        current = get_project_v2(project["id"], "user_a")
        edited = {
            **current["data"],
            "slides": [{"id": "sl0"}],
            "sentences": [{"id": "s1", "slide_idx": 0, "text": "確認済み台本"}],
            "highlights": [
                {"id": "h1", "slide_idx": 0, "x": 10, "y": 20, "w": 30, "h": 40, "kind": "marker"}
            ],
        }
        saved = save_project_draft(
            project_id=project["id"],
            user_id="user_a",
            base_version=current["draft_version"],
            state=edited,
        )
        layout = confirm_review_stage(
            project_id=project["id"],
            user_id="user_a",
            run_id=run["id"],
            stage="layout",
            draft_version=saved["draft_version"],
        )
        script = confirm_review_stage(
            project_id=project["id"],
            user_id="user_a",
            run_id=run["id"],
            stage="script",
            draft_version=layout["revision"]["draft_version"],
        )
        context = get_review_assignment_context(
            project_id=project["id"],
            user_id="user_a",
            run_id=run["id"],
        )
        self.assertEqual(context["highlights"][0]["x"], 10)
        self.assertEqual(context["sentences"][0]["text"], "確認済み台本")
        confirm_review_stage(
            project_id=project["id"],
            user_id="user_a",
            run_id=run["id"],
            stage="assignment",
            draft_version=script["revision"]["draft_version"],
        )
        render_context = get_final_render_context(
            project_id=project["id"],
            user_id="user_a",
            run_id=run["id"],
        )
        self.assertEqual(render_context["assignment_revision_id"], get_project_v2(
            project["id"],
            "user_a",
        )["review_states"]["assignment"]["revision_id"])
        preview_file = Path(self.temp_dir.name) / "preview.mp3"
        preview_file.write_bytes(b"test-audio")
        preview = publish_preview_audio_result(
            project_id=project["id"],
            run_id=run["id"],
            user_id="user_a",
            job_id=None,
            preview_id="pa_preview_test",
            clip_path=preview_file,
            cache_key="preview-test",
            scope="all",
            duration=1.5,
            sentence_timings=[{"sentence_id": "s1", "start_sec": 0, "end_sec": 1.5}],
            clip_cache_hit=False,
            sentence_cache_hits=0,
            sentence_count=1,
        )
        self.assertEqual(preview["audio_artifact"]["status"], "active")
        self.assertEqual(preview["manifest_artifact"]["status"], "active")
        reused_preview = publish_preview_audio_result(
            project_id=project["id"],
            run_id=run["id"],
            user_id="user_a",
            job_id=None,
            preview_id="pa_preview_test_reused",
            clip_path=preview_file,
            cache_key="preview-test",
            scope="all",
            duration=1.5,
            sentence_timings=[{"sentence_id": "s1", "start_sec": 0, "end_sec": 1.5}],
            clip_cache_hit=True,
            sentence_cache_hits=1,
            sentence_count=1,
        )
        self.assertTrue(reused_preview["reused"])
        self.assertEqual(
            reused_preview["audio_artifact"]["id"],
            preview["audio_artifact"]["id"],
        )
        self.assertEqual(reused_preview["manifest_artifact"]["status"], "active")
        self.assertTrue(reused_preview["result"]["cache_hit"])
        render_file = Path(self.temp_dir.name) / "lecture.mp4"
        render_file.write_bytes(b"test-video")
        for kind in ("final_render", "final_render_manifest"):
            stored_render = get_artifact_store().put_file(
                render_file,
                project_id=project["id"],
                run_id=run["id"],
                stage="final_render",
                original_filename=f"{kind}.mp4",
                media_type="video/mp4",
            )
            register_stored_file(
                stored_render,
                project_id=project["id"],
                user_id="user_a",
                artifact_kind=kind,
                stage="final_render",
                run_id=run["id"],
            )

        changed = get_project_v2(project["id"], "user_a")
        changed_state = {
            **changed["data"],
            "sentences": [{**changed["data"]["sentences"][0], "text": "変更後"}],
        }
        changed_saved = save_project_draft(
            project_id=project["id"],
            user_id="user_a",
            base_version=changed["draft_version"],
            state=changed_state,
        )
        with self.assertRaises(ApiError) as invalid_assignment:
            confirm_review_stage(
                project_id=project["id"],
                user_id="user_a",
                run_id=run["id"],
                stage="assignment",
                draft_version=changed_saved["draft_version"],
            )
        self.assertEqual(invalid_assignment.exception.code, "REVIEW_STAGE_ORDER_INVALID")
        with self.assertRaises(ApiError) as stale:
            get_review_assignment_context(
                project_id=project["id"],
                user_id="user_a",
                run_id=run["id"],
            )
        self.assertEqual(stale.exception.code, "REVIEW_STAGE_NOT_CONFIRMED")
        with self.assertRaises(ApiError) as render_stale:
            get_final_render_context(
                project_id=project["id"],
                user_id="user_a",
                run_id=run["id"],
            )
        self.assertEqual(render_stale.exception.code, "REVIEW_STAGE_NOT_CONFIRMED")
        with db_conn() as conn:
            statuses = conn.execute(
                """
                SELECT artifact_kind, status FROM artifacts
                WHERE project_id = :project_id
                  AND artifact_kind IN ('final_render', 'final_render_manifest')
                """,
                {"project_id": project["id"]},
            ).fetchall()
        self.assertEqual({row["status"] for row in statuses}, {"stale"})
        with db_conn() as conn:
            preview_statuses = conn.execute(
                """
                SELECT artifact_kind, status FROM artifacts
                WHERE project_id = :project_id
                  AND artifact_kind IN ('preview_audio', 'preview_audio_manifest')
                """,
                {"project_id": project["id"]},
            ).fetchall()
        self.assertEqual({row["status"] for row in preview_statuses}, {"stale"})

    def test_preview_audio_requests_with_same_script_share_one_job(self) -> None:
        project, uploaded = self._project_with_pdf()
        run = create_generation_run_v2(
            project_id=project["id"],
            user_id="user_a",
            experiment_id=None,
            source_artifact_id=uploaded["artifact"]["id"],
            mode="hl",
            detail="standard",
            difficulty="basic",
            usage_context="general",
            conditions={},
        )
        request = PreviewAudioRequest(
            project_id=project["id"],
            run_id=run["id"],
            scope="all",
            sentences=[
                {
                    "id": "s1",
                    "slide_idx": 0,
                    "text": "同じ台本です。",
                    "start_sec": 0,
                    "end_sec": 2,
                }
            ],
        )
        manager = JobManager()
        first = manager.submit_preview_audio(
            request,
            owner_user_id="user_a",
            owner_session_id="session_a",
        )
        second = manager.submit_preview_audio(
            request,
            owner_user_id="user_a",
            owner_session_id="session_a",
        )
        self.assertEqual(first["job_id"], second["job_id"])
        self.assertTrue(second["deduplicated"])

    def test_sentence_audio_cache_regenerates_only_changed_text(self) -> None:
        generated_texts = []

        class FakeResponse:
            def __init__(self, text):
                self.text = text

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

            def stream_to_file(self, path):
                generated_texts.append(self.text)
                Path(path).write_bytes(f"audio:{self.text}".encode("utf-8"))

        class FakeStreamingResponse:
            @staticmethod
            def create(*, input, **_):
                return FakeResponse(input)

        class FakeSpeech:
            with_streaming_response = FakeStreamingResponse()

        class FakeAudio:
            speech = FakeSpeech()

        class FakeClient:
            audio = FakeAudio()

        client = FakeClient()
        first_a = ensure_preview_sentence_audio(
            {"client": client},
            {"id": "s1", "text": "変更しない文。"},
        )
        first_b = ensure_preview_sentence_audio(
            {"client": client},
            {"id": "s2", "text": "変更前の文。"},
        )
        second_a = ensure_preview_sentence_audio(
            {"client": client},
            {"id": "s1", "text": "変更しない文。"},
        )
        second_b = ensure_preview_sentence_audio(
            {"client": client},
            {"id": "s2", "text": "変更後の文。"},
        )

        self.assertFalse(first_a["cache_hit"])
        self.assertFalse(first_b["cache_hit"])
        self.assertTrue(second_a["cache_hit"])
        self.assertFalse(second_b["cache_hit"])
        self.assertEqual(
            generated_texts,
            ["変更しない文。", "変更前の文。", "変更後の文。"],
        )


if __name__ == "__main__":
    unittest.main()
