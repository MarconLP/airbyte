#
# Copyright (c) 2023 Airbyte, Inc., all rights reserved.
#

import logging
from typing import Any, Iterable, List, Mapping, Optional, Union
from unittest.mock import Mock

import pytest
from airbyte_cdk.models import AirbyteLogMessage, AirbyteMessage, Level, SyncMode
from airbyte_cdk.models import Type as MessageType
from airbyte_cdk.sources.streams import Stream
from airbyte_cdk.sources.streams.concurrent.thread_based_concurrent_stream import ThreadBasedConcurrentStream
from airbyte_cdk.sources.streams.core import StreamData
from airbyte_cdk.sources.utils.schema_helpers import InternalConfig
from airbyte_cdk.sources.utils.slice_logger import DebugSliceLogger

_A_CURSOR_FIELD = ["NESTED", "CURSOR"]
_DEFAULT_INTERNAL_CONFIG = InternalConfig()
_STREAM_NAME = "STREAM"


class _MockStream(Stream):
    def __init__(self, slice_to_records: Mapping[str, List[Mapping[str, Any]]]):
        self._slice_to_records = slice_to_records

    @property
    def primary_key(self) -> Optional[Union[str, List[str], List[List[str]]]]:
        return None

    def stream_slices(
        self, *, sync_mode: SyncMode, cursor_field: Optional[List[str]] = None, stream_state: Optional[Mapping[str, Any]] = None
    ) -> Iterable[Optional[Mapping[str, Any]]]:
        for partition in self._slice_to_records.keys():
            yield {"partition": partition}

    def read_records(
        self,
        sync_mode: SyncMode,
        cursor_field: Optional[List[str]] = None,
        stream_slice: Optional[Mapping[str, Any]] = None,
        stream_state: Optional[Mapping[str, Any]] = None,
    ) -> Iterable[StreamData]:
        yield from self._slice_to_records[stream_slice["partition"]]

    def get_json_schema(self) -> Mapping[str, Any]:
        return {}


def _legacy_stream(slice_to_partition_mapping, slice_logger, logger):
    return _MockStream(slice_to_partition_mapping)


def _concurrent_stream(slice_to_partition_mapping, slice_logger, logger):
    legacy_stream = _legacy_stream(slice_to_partition_mapping, slice_logger, logger)
    source = Mock()
    stream = ThreadBasedConcurrentStream.create_from_legacy_stream(legacy_stream, source, 1, slice_logger)
    stream.logger.setLevel(logger.level)
    return stream


@pytest.mark.parametrize(
    "constructor",
    [
        pytest.param(_legacy_stream, id="synchronous_reader"),
        pytest.param(_concurrent_stream, id="concurrent_reader"),
    ],
)
def test_full_refresh_read_a_single_slice_with_debug(constructor):
    # This test verifies that a concurrent stream adapted from a legacy stream behaves the same as the legacy stream
    # It is done by running the same test cases on both streams
    records = [
        {"id": 1, "partition": 1},
        {"id": 2, "partition": 1},
    ]
    slice_to_partition = {1: records}
    slice_logger = DebugSliceLogger()
    logger = _mock_logger(True)
    stream = constructor(slice_to_partition, slice_logger, logger)

    expected_records = [
        AirbyteMessage(
            type=MessageType.LOG,
            log=AirbyteLogMessage(
                level=Level.INFO,
                message='slice:{"partition": 1}',
            ),
        ),
        *records,
    ]

    actual_records = list(stream.read_full_refresh(_A_CURSOR_FIELD, logger, slice_logger))

    assert expected_records == actual_records


@pytest.mark.parametrize(
    "constructor",
    [
        pytest.param(_legacy_stream, id="synchronous_reader"),
        pytest.param(_concurrent_stream, id="concurrent_reader"),
    ],
)
def test_full_refresh_read_a_single_slice(constructor):
    # This test verifies that a concurrent stream adapted from a legacy stream behaves the same as the legacy stream
    # It is done by running the same test cases on both streams
    logger = _mock_logger()
    slice_logger = DebugSliceLogger()

    records = [
        {"id": 1, "partition": 1},
        {"id": 2, "partition": 1},
    ]
    slice_to_partition = {1: records}
    stream = constructor(slice_to_partition, slice_logger, logger)

    expected_records = [*records]

    actual_records = list(stream.read_full_refresh(_A_CURSOR_FIELD, logger, slice_logger))

    assert expected_records == actual_records


@pytest.mark.parametrize(
    "constructor",
    [
        pytest.param(_legacy_stream, id="synchronous_reader"),
        pytest.param(_concurrent_stream, id="concurrent_reader"),
    ],
)
def test_full_refresh_read_a_two_slices(constructor):
    # This test verifies that a concurrent stream adapted from a legacy stream behaves the same as the legacy stream
    # It is done by running the same test cases on both streams
    logger = _mock_logger()
    slice_logger = DebugSliceLogger()

    records_partition_1 = [
        {"id": 1, "partition": 1},
        {"id": 2, "partition": 1},
    ]
    records_partition_2 = [
        {"id": 3, "partition": 2},
        {"id": 4, "partition": 2},
    ]
    slice_to_partition = {1: records_partition_1, 2: records_partition_2}
    stream = constructor(slice_to_partition, slice_logger, logger)

    expected_records = [
        *records_partition_1,
        *records_partition_2,
    ]

    actual_records = list(stream.read_full_refresh(_A_CURSOR_FIELD, logger, slice_logger))

    for record in expected_records:
        assert record in actual_records
    assert len(expected_records) == len(actual_records)


def _mock_partition_generator(name: str, slices, records_per_partition, *, available=True, debug_log=False):
    stream = Mock()
    stream.name = name
    stream.get_json_schema.return_value = {}
    stream.generate_partitions.return_value = iter(slices)
    stream.read_records.side_effect = [iter(records) for records in records_per_partition]
    stream.logger.isEnabledFor.return_value = debug_log
    if available:
        stream.check_availability.return_value = True, None
    else:
        stream.check_availability.return_value = False, "A reason why the stream is unavailable"
    return stream


def _mock_logger(enabled_for_debug=False):
    logger = Mock()
    logger.isEnabledFor.return_value = enabled_for_debug
    logger.level = logging.DEBUG if enabled_for_debug else logging.INFO
    return logger
