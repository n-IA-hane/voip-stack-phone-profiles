# SPDX-License-Identifier: MIT
import pytest

from phone_profiles.import_fusionpbx import import_archive


def test_untrusted_archive_rejected_before_any_filesystem_write(tmp_path):
    destination = tmp_path / "uncreated"
    with pytest.raises(ValueError, match="hash mismatch"):
        import_archive(b"not the fixed upstream archive", destination)
    assert not destination.exists()
