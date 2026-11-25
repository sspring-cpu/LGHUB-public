"""Authenticated Streamlit wrapper for the existing LG RMA Hub."""

from __future__ import annotations

import base64
import json
import mimetypes
import zlib
from pathlib import Path, PurePosixPath
from typing import Any


APP_DIR = Path(__file__).resolve().parent
BOOTSTRAP_MARKER = "<!-- ===================== RMA LOOKUP SCRIPT ===================== -->"


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as file:
        return json.load(file)


def _find_image_paths(value: Any):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _find_image_paths(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _find_image_paths(nested)
    elif isinstance(value, str) and value.startswith("img/"):
        yield value


def _image_data_uri(root: Path, source: str) -> str:
    relative = PurePosixPath(source)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "img":
        raise ValueError(f"Invalid image path in troubleshooting data: {source}")

    image_root = (root / "img").resolve()
    image_path = (root.joinpath(*relative.parts)).resolve()
    try:
        image_path.relative_to(image_root)
    except ValueError as exc:
        raise ValueError(f"Image path is outside the image directory: {source}") from exc

    media_type, _ = mimetypes.guess_type(image_path.name)
    if not media_type or not media_type.startswith("image/"):
        raise ValueError(f"Unsupported image type: {source}")
    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
    return f"data:{media_type};base64,{encoded}"


def build_authenticated_html(root: Path = APP_DIR) -> str:
    """Build the existing browser app with its data bundled behind the auth gate."""
    root = Path(root)
    troubleshooting_data = _read_json(root / "data.json")
    files = {
        "data.json": json.dumps(
            troubleshooting_data, ensure_ascii=False, separators=(",", ":")
        )
    }

    image_paths = set(_find_image_paths(troubleshooting_data))
    images = {
        source: _image_data_uri(root, source)
        for source in sorted(image_paths)
    }

    bundle = json.dumps(
        {"files": files, "images": images},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")
    compressed_bundle = base64.b64encode(zlib.compress(bundle, level=9)).decode("ascii")
    bootstrap = f"""
<script>
let __lgRmaBundle;
const __lgRmaBundlePromise = (async function() {{
  if (!window.DecompressionStream) throw new Error('This browser does not support compressed app data.');
  const compressed = Uint8Array.from(atob('{compressed_bundle}'), char => char.charCodeAt(0));
  const stream = new Blob([compressed]).stream().pipeThrough(new DecompressionStream('deflate'));
  return JSON.parse(await new Response(stream).text());
}})().then(bundle => (__lgRmaBundle = bundle));
window.__lgRmaUnavailable = true;
const __lgRmaFetch = window.fetch.bind(window);
function __lgRmaInlineImages(value) {{
  if (typeof value === 'string' && Object.prototype.hasOwnProperty.call(__lgRmaBundle.images, value)) {{
    return __lgRmaBundle.images[value];
  }}
  if (Array.isArray(value)) return value.map(__lgRmaInlineImages);
  if (value && typeof value === 'object') {{
    const result = {{}};
    Object.keys(value).forEach(key => result[key] = __lgRmaInlineImages(value[key]));
    return result;
  }}
  return value;
}}
window.fetch = async function(input, init) {{
  await __lgRmaBundlePromise;
  const url = (typeof input === 'string' ? input : input.url).replace(/^\\.\\//, '');
  if (Object.prototype.hasOwnProperty.call(__lgRmaBundle.files, url)) {{
    const body = __lgRmaBundle.files[url];
    delete __lgRmaBundle.files[url];
    const contents = url === 'data.json'
      ? JSON.stringify(__lgRmaInlineImages(JSON.parse(body)))
      : body;
    return Promise.resolve(new Response(contents, {{
      status: 200,
      headers: {{'Content-Type': 'application/json'}}
    }}));
  }}
  return __lgRmaFetch(input, init);
}};
</script>
"""

    html = (root / "index.html").read_text(encoding="utf-8")
    if html.count(BOOTSTRAP_MARKER) != 1:
        raise ValueError("Could not locate the RMA app data bootstrap point in index.html")
    return html.replace(BOOTSTRAP_MARKER, bootstrap + "\n" + BOOTSTRAP_MARKER, 1)


def main() -> None:
    import streamlit as st

    import auth

    st.set_page_config(page_title="LG RMA Hub", page_icon="🔋", layout="wide")
    verified_email = auth.require_auth()

    st.sidebar.success(f"Logged in as {verified_email}")
    if st.sidebar.button("Log out"):
        st.session_state.pop("auth_email", None)
        st.session_state.pop("auth_expires_at", None)
        st.rerun()

    st.iframe(
        build_authenticated_html(),
        height=1050,
        alt="LG RMA Hub lookup and troubleshooting tools",
    )


if __name__ == "__main__":
    main()
