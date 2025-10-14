"""
Graph schema definitions for CDR (Call Detail Record) data
"""

from typing import Dict, Any


def get_cdr_graph_schema() -> Dict[str, Any]:
    """
    Returns the graph schema based on redberry.fact_cdr table.

    This schema models telecommunications call detail records as a graph:
    - Vertices: subscriber, call_event
    - Edges: calls (subscriber -> call_event)
    """
    return {
        "vertices": [
            {
                "label": "subscriber",
                "oneToOne": {
                    "tableSource": {
                        "catalog": "redberry",
                        "schema": "redberry",
                        "table": "fact_cdr",
                    },
                    "id": {
                        "fields": [
                            {
                                "type": "UInt64",
                                "field": "a_subscriber_id",
                                "alias": "puppy_id_a_subscriber_id",
                            }
                        ]
                    },
                    "attributes": [
                        {
                            "type": "UInt64",
                            "field": "a_subscriber_id",
                            "alias": "a_subscriber_id",
                        },
                        {
                            "type": "String",
                            "field": "a_number",
                            "alias": "a_number",
                        },
                        {
                            "type": "String",
                            "field": "operator",
                            "alias": "operator",
                        },
                    ],
                },
            },
            {
                "label": "call_event",
                "oneToOne": {
                    "tableSource": {
                        "catalog": "redberry",
                        "schema": "redberry",
                        "table": "fact_cdr",
                    },
                    "id": {
                        "fields": [
                            {
                                "type": "UInt64",
                                "field": "event_id",
                                "alias": "puppy_id_event_id",
                            }
                        ]
                    },
                    "attributes": [
                        {
                            "type": "UInt64",
                            "field": "event_id",
                            "alias": "event_id",
                        },
                        {
                            "type": "String",
                            "field": "event_type",
                            "alias": "event_type",
                        },
                        {
                            "type": "DateTime",
                            "field": "event_datetime",
                            "alias": "event_datetime",
                        },
                        {
                            "type": "Int32",
                            "field": "duration_seconds",
                            "alias": "duration_seconds",
                        },
                        {
                            "type": "String",
                            "field": "b_number",
                            "alias": "b_number",
                        },
                        {
                            "type": "Float64",
                            "field": "latitude",
                            "alias": "latitude",
                        },
                        {
                            "type": "Float64",
                            "field": "longitude",
                            "alias": "longitude",
                        },
                    ],
                },
            },
        ],
        "edges": [
            {
                "label": "calls",
                "fromVertex": "subscriber",
                "toVertex": "call_event",
                "tableSource": {
                    "catalog": "redberry",
                    "schema": "redberry",
                    "table": "fact_cdr",
                },
                "id": {
                    "fields": [
                        {
                            "type": "UInt64",
                            "field": "event_id",
                            "alias": "puppy_id_event_id",
                        }
                    ]
                },
                "fromId": {
                    "fields": [
                        {
                            "type": "UInt64",
                            "field": "a_subscriber_id",
                            "alias": "puppy_from_a_subscriber_id",
                        }
                    ]
                },
                "toId": {
                    "fields": [
                        {
                            "type": "UInt64",
                            "field": "event_id",
                            "alias": "puppy_to_event_id",
                        }
                    ]
                },
                "attributes": [
                    {
                        "type": "String",
                        "field": "call_type",
                        "alias": "call_type",
                    },
                    {
                        "type": "DateTime",
                        "field": "event_datetime",
                        "alias": "event_datetime",
                    },
                ],
            }
        ],
    }
