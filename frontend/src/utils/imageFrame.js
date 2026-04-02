export function resolveImageSize(slide, naturalSize = null) {
  if (naturalSize?.width > 0 && naturalSize?.height > 0) {
    return { width: naturalSize.width, height: naturalSize.height };
  }
  const width = Number(slide?.width ?? 0);
  const height = Number(slide?.height ?? 0);
  if (width > 0 && height > 0) {
    return { width, height };
  }
  const aspect = Number(slide?.aspect_ratio ?? 0);
  if (aspect > 0) {
    return { width: aspect * 100, height: 100 };
  }
  return { width: 1600, height: 900 };
}

export function getContainRect(containerWidth, containerHeight, imageWidth, imageHeight) {
  if (!(containerWidth > 0) || !(containerHeight > 0) || !(imageWidth > 0) || !(imageHeight > 0)) {
    return { left: 0, top: 0, width: containerWidth, height: containerHeight };
  }
  const containerAspect = containerWidth / containerHeight;
  const imageAspect = imageWidth / imageHeight;

  if (imageAspect > containerAspect) {
    const width = containerWidth;
    const height = width / imageAspect;
    return {
      left: 0,
      top: (containerHeight - height) / 2,
      width,
      height,
    };
  }

  const height = containerHeight;
  const width = height * imageAspect;
  return {
    left: (containerWidth - width) / 2,
    top: 0,
    width,
    height,
  };
}
