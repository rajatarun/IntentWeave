import boto3
import moto
import pytest

from intentweave.errors import ThreadError
from intentweave.models import ThreadRecord
from intentweave.store.dynamodb import DynamoDBThreadStore


@pytest.fixture
def ddb_table():
    with moto.mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName="threads",
            KeySchema=[{"AttributeName": "response_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "response_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        yield DynamoDBThreadStore("threads", client=client)


def _sample_record(rid: str = "msg_abc") -> ThreadRecord:
    return ThreadRecord(
        response_id=rid,
        thread_id=rid,
        parent_response_id=None,
        fingerprint={"model": "m"},
        system="sys",
        tools=None,
        messages=[{"role": "user", "content": "hi"}],
        model="m",
        stop_reason="end_turn",
        assistant_message={"id": rid},
        last_used_epoch=1.0,
        ttl_epoch=9999,
    )


def test_dynamodb_round_trip(ddb_table: DynamoDBThreadStore):
    rec = _sample_record()
    ddb_table.put(rec)
    loaded = ddb_table.get("msg_abc")
    assert loaded is not None
    assert loaded.model == "m"


def test_dynamodb_continue_lock(ddb_table: DynamoDBThreadStore):
    ddb_table.put(_sample_record())
    ddb_table.try_begin_continue("msg_abc")
    with pytest.raises(ThreadError) as exc:
        ddb_table.try_begin_continue("msg_abc")
    assert exc.value.error_code == "thread_continue_in_flight"
