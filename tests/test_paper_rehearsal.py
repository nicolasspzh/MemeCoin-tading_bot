import pytest

from data.database import Database
from operations.paper_rehearsal import rehearse, worker


def test_real_process_crashes_and_backups_resume_without_duplicate_trades(tmp_path):
    result = rehearse(tmp_path / 'rehearsal')
    assert result['status'] == 'SYNTHETIC_OPERATIONAL_REHEARSAL_PASSED'
    assert result['network_requests'] == 0
    assert result['reference']['summary']['fills'] == 2
    assert result['reference']['summary']['snapshots'] == 18
    for stage in ('pending', 'position'):
        check = result['checks'][stage]
        assert check['exit_code'] == -9
        assert check['second_writer_excluded']
        assert check['resume_matches_continuous'] and check['restore_matches_continuous']
        assert check['repeated_resume_idempotent']
    assert result['checks']['quote_outage']['cash_usd'] == '50.00'
    assert not result['market_paper_service_started']


def test_rehearsal_refuses_existing_output_without_modification(tmp_path):
    marker = tmp_path / 'keep.txt'
    marker.write_text('preserve')
    with pytest.raises(FileExistsError):
        rehearse(tmp_path)
    assert list(tmp_path.iterdir()) == [marker]
    assert marker.read_text() == 'preserve'


def test_worker_rejects_market_database_before_opening_writer(tmp_path):
    path = tmp_path / 'market.sqlite3'
    Database(path, 'dexscreener').close()
    before = path.read_bytes()
    with pytest.raises(ValueError, match='synthetic'):
        worker(path)
    assert path.read_bytes() == before
    assert not (tmp_path / 'market.sqlite3.lock').exists()
