"""UI upload boundaries: limits and path checks apply before any file is written."""

import io
import zipfile

import pytest

from testpilot.errors import ProjectAnalysisError
from testpilot.tools import zip_project as uploads


def archive_of(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files:
            info = zipfile.ZipInfo("placeholder")
            info.filename = name  # Preserve raw unsafe names even on Windows.
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data)
    return buffer.getvalue()


def test_directory_restores_nested_structure(tmp_path):
    root = uploads.extract_directory(
        [("project/src/pkg/module.py", b"x = 1\n"), ("project/README.md", b"project")], tmp_path
    )
    assert root == tmp_path / "project"
    assert (root / "src/pkg/module.py").read_bytes() == b"x = 1\n"


@pytest.mark.parametrize(
    "name",
    [
        "../a.py",
        "/a.py",
        "C:/a.py",
        "a\\b.py",
        "a:stream.py",
        "NUL.py",
        "a /x.py",
        "a./x.py",
        "a/../b.py",
        "./a.py",
        "a//b.py",
        "a\x00b.py",
    ],
)
@pytest.mark.parametrize("kind", ["zip", "directory"])
def test_all_uploads_reject_unsafe_paths_before_writing(tmp_path, name, kind):
    files = [("safe.py", b"x=1"), (name, b"x=2")]
    with pytest.raises(ProjectAnalysisError, match="路径不安全"):
        if kind == "zip":
            uploads.extract_project(archive_of(files), tmp_path)
        else:
            uploads.extract_directory(files, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("names", [("A.py", "a.py"), ("a", "a/b.py"), ("A/x.py", "a/y.py")])
@pytest.mark.parametrize("kind", ["zip", "directory"])
def test_upload_collisions(tmp_path, names, kind):
    files = [(name, b"x") for name in names]
    with pytest.raises(ProjectAnalysisError, match="路径不安全"):
        if kind == "zip":
            uploads.extract_project(archive_of(files), tmp_path)
        else:
            uploads.extract_directory(files, tmp_path)
    assert not list(tmp_path.iterdir())


def test_zip_compressed_size_limit(tmp_path):
    # Checked before parsing, so no need to allocate a large valid archive.
    with pytest.raises(ProjectAnalysisError, match="上传文件过大"):
        uploads.extract_project(b"0" * (uploads.MAX_PROJECT_BYTES + 1), tmp_path)
    assert not list(tmp_path.iterdir())


def test_zip_expanded_size_limit(tmp_path):
    data = archive_of([("large.py", b"0" * (uploads.MAX_PROJECT_BYTES + 1))])
    assert len(data) < uploads.MAX_PROJECT_BYTES
    with pytest.raises(ProjectAnalysisError, match="解压后项目过大"):
        uploads.extract_project(data, tmp_path)
    assert not list(tmp_path.iterdir())


def test_directory_total_size_limit(tmp_path):
    # Each file is below the limit; the aggregate is not.
    half = b"x" * (uploads.MAX_PROJECT_BYTES // 2 + 1)
    with pytest.raises(ProjectAnalysisError, match="上传文件过大"):
        uploads.extract_directory([("a.py", half), ("b.py", half)], tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("kind", ["zip", "directory"])
def test_upload_file_count_limit(tmp_path, kind):
    files = [(f"{i}.py", b"") for i in range(uploads.MAX_PROJECT_FILES + 1)]
    with pytest.raises(ProjectAnalysisError, match="文件数量过多"):
        if kind == "zip":
            uploads.extract_project(archive_of(files), tmp_path)
        else:
            uploads.extract_directory(files, tmp_path)
    assert not list(tmp_path.iterdir())


def test_directory_existing_symlink_rejected(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires platform privileges")
    with pytest.raises(ProjectAnalysisError, match="路径不安全"):
        uploads.extract_directory([("link/a.py", b"x")], tmp_path)
    assert not (target / "a.py").exists()
