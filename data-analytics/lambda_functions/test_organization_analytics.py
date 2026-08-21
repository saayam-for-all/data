import pytest
import organization_analytics
from unittest.mock import Mock
from datetime import datetime
import json

def test_build_filters_all():
    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == []
    assert params == []


def test_build_filters_organization_type():
    filters = {
        "time_filter": "ALL",
        "organization_type": "non_profit",
        "region": "ALL"
    }
 
    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == ["o.org_type = %s"]
    assert params == ["Non-Profit"]    


def test_build_filters_for_profit():
    filters = {
        "time_filter": "ALL",
        "organization_type": "for_profit",
        "region": "ALL"
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == ["o.org_type = %s"]
    assert params == ["For-profit"]


def test_build_filters_region():
    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "California"
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == [
        "o.state_id = (SELECT s.state_id FROM virginia_dev_saayam_rdbms.state s WHERE s.state_name = %s)"
    ]
    assert params == ["California"]


def test_build_filters_org_size():
    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "org_size": "Large"
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == ["o.org_size = %s"]
    assert params == ["Large"]    


def test_build_filters_state_id():
    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "state_id": 10
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == ["o.state_id = %s"]
    assert params == [10]    


def test_build_filters_city():
    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "city_name": "New Susanville"
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == ["o.city_name = %s"]
    assert params == ["New Susanville"]    


def test_build_filters_rating():
    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "org_rating": 5
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == ["o.org_rating = %s"]
    assert params == [5]    


def test_build_filters_collaborator():
    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "is_collaborator": True
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == ["o.is_collaborator = %s"]
    assert params == [True]    


def test_build_filters_contributor():
    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "is_contributor": True
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == ["o.is_contributor = %s"]
    assert params == [True]    


def test_build_filters_7d():
    filters = {
        "time_filter": "7D",
        "organization_type": "ALL",
        "region": "ALL"
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == [
        "o.created_at >= CURRENT_DATE - INTERVAL '7 days'"
    ]
    assert params == []    


def test_build_filters_30d():
    filters = {
        "time_filter": "30D",
        "organization_type": "ALL",
        "region": "ALL"
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == [
        "o.created_at >= CURRENT_DATE - INTERVAL '30 days'"
    ]
    assert params == []    


def test_build_filters_1y():
    filters = {
        "time_filter": "1Y",
        "organization_type": "ALL",
        "region": "ALL"
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == [
        "o.created_at >= CURRENT_DATE - INTERVAL '1 year'"
    ]
    assert params == []    


def test_build_filters_custom():
    filters = {
        "time_filter": "CUSTOM",
        "start_date": "2026-01-01",
        "end_date": "2026-06-30",
        "organization_type": "ALL",
        "region": "ALL"
    }

    conditions, params = organization_analytics.build_filters(filters)

    assert conditions == [
        "o.created_at >= %s AND o.created_at < (%s::date + INTERVAL '1 day')"
    ]

    assert params == [
        "2026-01-01",
        "2026-06-30"
    ]    


def test_build_filters_custom_missing_dates():
    filters = {
        "time_filter": "CUSTOM",
        "start_date": None,
        "end_date": None,
        "organization_type": "ALL",
        "region": "ALL"
    }

    with pytest.raises(ValueError, match="start_date and end_date are required"):
        organization_analytics.build_filters(filters)    


def test_build_filters_custom_missing_start_date():
    filters = {
        "time_filter": "CUSTOM",
        "start_date": None,
        "end_date": "2026-06-30",
        "organization_type": "ALL",
        "region": "ALL"
    }

    with pytest.raises(ValueError, match="start_date and end_date are required"):
        organization_analytics.build_filters(filters)        


def test_build_filters_custom_missing_end_date():
    filters = {
        "time_filter": "CUSTOM",
        "start_date": "2026-01-01",
        "end_date": None,
        "organization_type": "ALL",
        "region": "ALL"
    }

    with pytest.raises(ValueError, match="start_date and end_date are required"):
        organization_analytics.build_filters(filters)        


def test_fetch_organization_summary_normal_values():
    mock_cursor = Mock()

    mock_cursor.fetchone.return_value = {
        "total_organizations": 10,
        "total_collaborators": 4,
        "total_contributors": 6,
        "average_org_rating": 4.2
    }

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_organization_summary(
        mock_cursor,
        filters
    )

    assert result == {
        "total_organizations": 10,
        "total_collaborators": 4,
        "total_contributors": 6,
        "average_org_rating": 4.2
    }

    mock_cursor.execute.assert_called_once()   


def test_fetch_organization_summary_null_average_rating():
    mock_cursor = Mock()

    mock_cursor.fetchone.return_value = {
        "total_organizations": 5,
        "total_collaborators": 2,
        "total_contributors": 3,
        "average_org_rating": None
    }

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_organization_summary(
        mock_cursor,
        filters
    )

    assert result == {
        "total_organizations": 5,
        "total_collaborators": 2,
        "total_contributors": 3,
        "average_org_rating": 0
    }   


def test_fetch_organization_summary_response_structure():
    mock_cursor = Mock()

    mock_cursor.fetchone.return_value = {
        "total_organizations": 20,
        "total_collaborators": 8,
        "total_contributors": 12,
        "average_org_rating": 3.75
    }

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_organization_summary(
        mock_cursor,
        filters
    )

    assert set(result.keys()) == {
        "total_organizations",
        "total_collaborators",
        "total_contributors",
        "average_org_rating"
    }

    assert isinstance(result["total_organizations"], int)
    assert isinstance(result["total_collaborators"], int)
    assert isinstance(result["total_contributors"], int)
    assert isinstance(result["average_org_rating"], float)   


def test_fetch_growth_trend_daily():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "period": "2026-01-01",
            "total_organizations": 3,
            "total_collaborators": 2
        },
        {
            "period": "2026-01-02",
            "total_organizations": 2,
            "total_collaborators": 1
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "daily"
    }

    result = organization_analytics.fetch_growth_trend(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "period": "2026-01-01",
            "total_organizations": 3,
            "total_collaborators": 2
        },
        {
            "period": "2026-01-02",
            "total_organizations": 2,
            "total_collaborators": 1
        }
    ]

    mock_cursor.execute.assert_called_once() 


def test_fetch_growth_trend_weekly():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "period": "2026-01-05 00:00:00",
            "total_organizations": 4,
            "total_collaborators": 2
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "weekly"
    }

    result = organization_analytics.fetch_growth_trend(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "period": "2026-01-05 00:00:00",
            "total_organizations": 4,
            "total_collaborators": 2
        }
    ]

    mock_cursor.execute.assert_called_once()     


def test_fetch_growth_trend_monthly():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "period": "2026-01-01 00:00:00",
            "total_organizations": 5,
            "total_collaborators": 3
        },
        {
            "period": "2026-02-01 00:00:00",
            "total_organizations": 2,
            "total_collaborators": 1
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "monthly"
    }

    result = organization_analytics.fetch_growth_trend(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "period": "2026-01-01 00:00:00",
            "total_organizations": 5,
            "total_collaborators": 3
        },
        {
            "period": "2026-02-01 00:00:00",
            "total_organizations": 2,
            "total_collaborators": 1
        }
    ]

    mock_cursor.execute.assert_called_once()  


def test_fetch_growth_trend_yearly():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "period": "2026-01-01 00:00:00",
            "total_organizations": 12,
            "total_collaborators": 7
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "yearly"
    }

    result = organization_analytics.fetch_growth_trend(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "period": "2026-01-01 00:00:00",
            "total_organizations": 12,
            "total_collaborators": 7
        }
    ]

    mock_cursor.execute.assert_called_once()   


def test_fetch_growth_trend_invalid_group_by():
    mock_cursor = Mock()

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "invalid"
    }

    with pytest.raises(
        ValueError,
        match="Invalid group_by"
    ):
        organization_analytics.fetch_growth_trend(
            mock_cursor,
            filters
        )

    mock_cursor.execute.assert_not_called()


def test_fetch_organizations_by_size_normal():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "org_size": "Large",
            "organization_count": 7
        },
        {
            "org_size": "Small",
            "organization_count": 2
        },
        {
            "org_size": "Medium",
            "organization_count": 2
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_organizations_by_size(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "org_size": "Large",
            "organization_count": 7
        },
        {
            "org_size": "Small",
            "organization_count": 2
        },
        {
            "org_size": "Medium",
            "organization_count": 2
        }
    ]


def test_fetch_organizations_by_size_empty():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = []

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_organizations_by_size(
        mock_cursor,
        filters
    )

    assert result == []


def test_fetch_collaborator_vs_contributor_normal():
    mock_cursor = Mock()

    mock_cursor.fetchone.return_value = {
        "collaborator_count": 21,
        "contributor_count": 19
    }

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_collaborator_vs_contributor(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "type": "collaborator",
            "organization_count": 21,
            "percentage": 52.5
        },
        {
            "type": "contributor",
            "organization_count": 19,
            "percentage": 47.5
        }
    ]


def test_fetch_collaborator_vs_contributor_zero_total():
    mock_cursor = Mock()

    mock_cursor.fetchone.return_value = {
        "collaborator_count": 0,
        "contributor_count": 0
    }

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_collaborator_vs_contributor(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "type": "collaborator",
            "organization_count": 0,
            "percentage": 0
        },
        {
            "type": "contributor",
            "organization_count": 0,
            "percentage": 0
        }
    ]                      


def test_fetch_organizations_by_location_normal():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "state_code": "US-TX",
            "state_name": "Texas",
            "total_organizations": 3
        },
        {
            "state_code": "US-MI",
            "state_name": "Michigan",
            "total_organizations": 2
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_organizations_by_location(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "state_code": "US-TX",
            "state_name": "Texas",
            "total_organizations": 3
        },
        {
            "state_code": "US-MI",
            "state_name": "Michigan",
            "total_organizations": 2
        }
    ]

    mock_cursor.execute.assert_called_once()


def test_fetch_organizations_by_location_empty():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = []

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_organizations_by_location(
        mock_cursor,
        filters
    )

    assert result == []

    mock_cursor.execute.assert_called_once()


def test_fetch_organizations_by_location_structure():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "state_code": "US-CA",
            "state_name": "California",
            "total_organizations": 1
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_organizations_by_location(
        mock_cursor,
        filters
    )

    assert len(result) == 1

    assert set(result[0].keys()) == {
        "state_code",
        "state_name",
        "total_organizations"
    }

    assert result[0]["state_code"] == "US-CA"
    assert result[0]["state_name"] == "California"
    assert result[0]["total_organizations"] == 1    


def test_fetch_rating_distribution_normal():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "rating": 1,
            "organization_count": 3
        },
        {
            "rating": 2,
            "organization_count": 2
        },
        {
            "rating": 3,
            "organization_count": 3
        },
        {
            "rating": 4,
            "organization_count": 1
        },
        {
            "rating": 5,
            "organization_count": 2
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_rating_distribution(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "rating": 1,
            "organization_count": 3
        },
        {
            "rating": 2,
            "organization_count": 2
        },
        {
            "rating": 3,
            "organization_count": 3
        },
        {
            "rating": 4,
            "organization_count": 1
        },
        {
            "rating": 5,
            "organization_count": 2
        }
    ]

    mock_cursor.execute.assert_called_once()    


def test_fetch_rating_distribution_empty():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = []

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_rating_distribution(
        mock_cursor,
        filters
    )

    assert result == []

    mock_cursor.execute.assert_called_once()    


def test_fetch_rating_distribution_converts_rating_to_int():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "rating": 5.0,
            "organization_count": 2
        },
        {
            "rating": 3.0,
            "organization_count": 4
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL"
    }

    result = organization_analytics.fetch_rating_distribution(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "rating": 5,
            "organization_count": 2
        },
        {
            "rating": 3,
            "organization_count": 4
        }
    ]

    assert isinstance(result[0]["rating"], int)
    assert isinstance(result[1]["rating"], int)    


def test_fetch_organization_type_distribution_daily():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "period": datetime(2026, 1, 10, 0, 0, 0),
            "for_profit": 1,
            "non_profit": 2,
            "total": 3
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "daily"
    }

    result = organization_analytics.fetch_organization_type_distribution(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "period": "2026-01-10",
            "for_profit": 1,
            "non_profit": 2,
            "total": 3
        }
    ]

    mock_cursor.execute.assert_called_once()    


def test_fetch_organization_type_distribution_weekly():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "period": datetime(2026, 1, 5, 0, 0, 0),
            "for_profit": 2,
            "non_profit": 3,
            "total": 5
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "weekly"
    }

    result = organization_analytics.fetch_organization_type_distribution(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "period": "2026-01-05 00:00:00",
            "for_profit": 2,
            "non_profit": 3,
            "total": 5
        }
    ]    


def test_fetch_organization_type_distribution_monthly():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "period": datetime(2026, 1, 1, 0, 0, 0),
            "for_profit": 0,
            "non_profit": 1,
            "total": 1
        },
        {
            "period": datetime(2025, 12, 1, 0, 0, 0),
            "for_profit": 1,
            "non_profit": 2,
            "total": 3
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "monthly"
    }

    result = organization_analytics.fetch_organization_type_distribution(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "period": "2026-01",
            "for_profit": 0,
            "non_profit": 1,
            "total": 1
        },
        {
            "period": "2025-12",
            "for_profit": 1,
            "non_profit": 2,
            "total": 3
        }
    ]    


def test_fetch_organization_type_distribution_yearly():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "period": datetime(2025, 1, 1, 0, 0, 0),
            "for_profit": 19,
            "non_profit": 20,
            "total": 39
        },
        {
            "period": datetime(2026, 1, 1, 0, 0, 0),
            "for_profit": 0,
            "non_profit": 1,
            "total": 1
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "yearly"
    }

    result = organization_analytics.fetch_organization_type_distribution(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "period": "2025",
            "for_profit": 19,
            "non_profit": 20,
            "total": 39
        },
        {
            "period": "2026",
            "for_profit": 0,
            "non_profit": 1,
            "total": 1
        }
    ]    


def test_fetch_organization_type_distribution_empty():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = []

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "monthly"
    }

    result = organization_analytics.fetch_organization_type_distribution(
        mock_cursor,
        filters
    )

    assert result == []

    mock_cursor.execute.assert_called_once()    


def test_fetch_organization_type_distribution_null_counts():
    mock_cursor = Mock()

    mock_cursor.fetchall.return_value = [
        {
            "period": datetime(2026, 1, 1, 0, 0, 0),
            "for_profit": None,
            "non_profit": None,
            "total": None
        }
    ]

    filters = {
        "time_filter": "ALL",
        "organization_type": "ALL",
        "region": "ALL",
        "group_by": "monthly"
    }

    result = organization_analytics.fetch_organization_type_distribution(
        mock_cursor,
        filters
    )

    assert result == [
        {
            "period": "2026-01",
            "for_profit": 0,
            "non_profit": 0,
            "total": 0
        }
    ]    


def test_lambda_handler_database_connection_failure(monkeypatch):

    def mock_connection_failure():
        raise Exception("Database connection failed")

    monkeypatch.setattr(
        organization_analytics,
        "get_db_connection",
        mock_connection_failure
    )

    result = organization_analytics.lambda_handler(
        {
            "time_filter": "ALL",
            "organization_type": "ALL",
            "region": "ALL"
        },
        None
    )

    assert result["statusCode"] == 500

    body = json.loads(result["body"])

    assert body["summary"]["total_organizations"] == 0
    assert body["growth_trend"] == []
    assert body["organizations_by_location"] == []


def test_lambda_handler_success(monkeypatch):

    class MockCursor:
        def close(self):
            pass

    class MockConnection:
        def cursor(self, cursor_factory=None):
            return MockCursor()

        def close(self):
            pass

    monkeypatch.setattr(
        organization_analytics,
        "get_db_connection",
        lambda: MockConnection()
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_organization_summary",
        lambda cursor, filters: {
            "total_organizations": 40,
            "total_collaborators": 21,
            "total_contributors": 19,
            "average_org_rating": 3.225
        }
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_growth_trend",
        lambda cursor, filters: [
            {
                "period": "2026-01-01",
                "total_organizations": 1,
                "total_collaborators": 0
            }
        ]
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_organizations_by_location",
        lambda cursor, filters: [
            {
                "state_code": "US-CA",
                "state_name": "California",
                "total_organizations": 1
            }
        ]
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_organizations_by_size",
        lambda cursor, filters: [
            {
                "org_size": "Large",
                "organization_count": 1
            }
        ]
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_collaborator_vs_contributor",
        lambda cursor, filters: [
            {
                "type": "collaborator",
                "organization_count": 1,
                "percentage": 100.0
            },
            {
                "type": "contributor",
                "organization_count": 0,
                "percentage": 0.0
            }
        ]
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_rating_distribution",
        lambda cursor, filters: [
            {
                "rating": 5,
                "organization_count": 1
            }
        ]
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_organization_type_distribution",
        lambda cursor, filters: [
            {
                "period": "2026-01",
                "for_profit": 0,
                "non_profit": 1,
                "total": 1
            }
        ]
    )

    result = organization_analytics.lambda_handler(
        {
            "time_filter": "ALL",
            "organization_type": "ALL",
            "region": "ALL",
            "group_by": "monthly"
        },
        None
    )

    assert result["statusCode"] == 200

    body = json.loads(result["body"])

    assert body["summary"]["total_organizations"] == 40
    assert body["summary"]["total_collaborators"] == 21
    assert body["summary"]["total_contributors"] == 19
    assert body["summary"]["average_org_rating"] == 3.225

    assert len(body["growth_trend"]) == 1
    assert len(body["organizations_by_location"]) == 1
    assert len(body["organizations_by_size"]) == 1
    assert len(body["collaborator_vs_contributor"]) == 2
    assert len(body["rating_distribution"]) == 1
    assert len(body["organization_type_distribution"]) == 1   


def test_lambda_handler_growth_trend_failure(monkeypatch):

    class MockCursor:
        def close(self):
            pass

    class MockConnection:
        def cursor(self, cursor_factory=None):
            return MockCursor()

        def close(self):
            pass

    monkeypatch.setattr(
        organization_analytics,
        "get_db_connection",
        lambda: MockConnection()
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_growth_trend",
        lambda cursor, filters: (
            (_ for _ in ()).throw(
                Exception("Growth query failed")
            )
        )
    )

    result = organization_analytics.lambda_handler(
        {
            "time_filter": "ALL",
            "organization_type": "ALL",
            "region": "ALL"
        },
        None
    )

    assert result["statusCode"] == 200

    body = json.loads(result["body"])

    assert body["growth_trend"] == []         


def test_lambda_handler_response_structure(monkeypatch):

    class MockCursor:
        def close(self):
            pass

    class MockConnection:
        def cursor(self, cursor_factory=None):
            return MockCursor()

        def close(self):
            pass

    monkeypatch.setattr(
        organization_analytics,
        "get_db_connection",
        lambda: MockConnection()
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_organization_summary",
        lambda cursor, filters: {
            "total_organizations": 0,
            "total_collaborators": 0,
            "total_contributors": 0,
            "average_org_rating": 0
        }
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_growth_trend",
        lambda cursor, filters: []
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_organizations_by_location",
        lambda cursor, filters: []
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_organizations_by_size",
        lambda cursor, filters: []
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_collaborator_vs_contributor",
        lambda cursor, filters: []
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_rating_distribution",
        lambda cursor, filters: []
    )

    monkeypatch.setattr(
        organization_analytics,
        "fetch_organization_type_distribution",
        lambda cursor, filters: []
    )

    result = organization_analytics.lambda_handler({}, None)

    assert result["statusCode"] == 200

    body = json.loads(result["body"])

    expected_keys = {
        "summary",
        "growth_trend",
        "organizations_by_location",
        "organizations_by_size",
        "collaborator_vs_contributor",
        "rating_distribution",
        "organization_type_distribution"
    }

    assert set(body.keys()) == expected_keys    