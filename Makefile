.PHONY: backend-setup backend frontend check-backend

backend-setup:
	bash scripts/setup_backend.sh

backend:
	bash scripts/dev_backend.sh

frontend:
	bash scripts/dev_frontend.sh

check-backend:
	bash scripts/check_backend.sh
