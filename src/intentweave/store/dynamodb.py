from typing import Any

import boto3
from botocore.exceptions import ClientError

from intentweave.errors import already_continued, continue_in_flight, thread_not_found
from intentweave.models import ThreadRecord


class DynamoDBThreadStore:
    """DynamoDB-backed thread store (one item per response id)."""

    def __init__(self, table_name: str, *, client: Any | None = None) -> None:
        self._table_name = table_name
        self._client = client or boto3.client("dynamodb")

    def _deserialize(self, item: dict[str, Any]) -> ThreadRecord:
        from boto3.dynamodb.types import TypeDeserializer

        deser = TypeDeserializer()
        plain = {k: deser.deserialize(v) for k, v in item.items()}
        return ThreadRecord.from_item(plain)

    def _serialize(self, record: ThreadRecord) -> dict[str, Any]:
        from decimal import Decimal

        from boto3.dynamodb.types import TypeSerializer

        ser = TypeSerializer()
        item = record.to_item()
        if isinstance(item.get("last_used_epoch"), float):
            item["last_used_epoch"] = Decimal(str(item["last_used_epoch"]))
        return {k: ser.serialize(v) for k, v in item.items()}

    def get(self, response_id: str) -> ThreadRecord | None:
        resp = self._client.get_item(
            TableName=self._table_name,
            Key={"response_id": {"S": response_id}},
        )
        item = resp.get("Item")
        if not item:
            return None
        return self._deserialize(item)

    def put(self, record: ThreadRecord) -> None:
        self._client.put_item(
            TableName=self._table_name,
            Item=self._serialize(record),
        )

    def try_begin_continue(self, response_id: str) -> ThreadRecord:
        try:
            resp = self._client.update_item(
                TableName=self._table_name,
                Key={"response_id": {"S": response_id}},
                UpdateExpression="SET continue_in_flight = :true",
                ConditionExpression=(
                    "attribute_exists(response_id) AND continued <> :true "
                    "AND (attribute_not_exists(continue_in_flight) OR continue_in_flight = :false)"
                ),
                ExpressionAttributeValues={
                    ":true": {"BOOL": True},
                    ":false": {"BOOL": False},
                },
                ReturnValues="ALL_NEW",
            )
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code")
            if code == "ConditionalCheckFailedException":
                existing = self.get(response_id)
                if existing is None:
                    raise thread_not_found() from exc
                if existing.continued:
                    raise already_continued() from exc
                if existing.continue_in_flight:
                    raise continue_in_flight() from exc
                raise thread_not_found() from exc
            raise
        return self._deserialize(resp["Attributes"])

    def finish_continue(
        self,
        parent_id: str,
        *,
        new_record: ThreadRecord,
        mark_parent_continued: bool,
    ) -> None:
        update = "SET continue_in_flight = :false, last_used_epoch = :lu, #ttl = :ttl" + (
            ", continued = :true" if mark_parent_continued else ""
        )
        expr_names = {"#ttl": "ttl"}
        values: dict[str, Any] = {
            ":false": {"BOOL": False},
            ":lu": {"N": str(new_record.last_used_epoch)},
            ":ttl": {"N": str(new_record.ttl_epoch)},
            ":true": {"BOOL": True},
        }
        self._client.update_item(
            TableName=self._table_name,
            Key={"response_id": {"S": parent_id}},
            UpdateExpression=update,
            ExpressionAttributeNames=expr_names,
            ExpressionAttributeValues=values,
        )
        self.put(new_record)

    def abort_continue(self, response_id: str) -> None:
        try:
            self._client.update_item(
                TableName=self._table_name,
                Key={"response_id": {"S": response_id}},
                UpdateExpression="SET continue_in_flight = :false",
                ExpressionAttributeValues={":false": {"BOOL": False}},
            )
        except ClientError:
            pass
