import json
import psycopg2
import os 

REAL_TABLE_STATE ="virginia_dev_saayam_rdbms.state"
REAL_TABLE_USERS ="virginia_dev_saayam_rdbms.users"
REAL_TABLE_VOLUNTEER_DETAILS ="virginia_dev_saayam_rdbms.volunteer_details"
REAL_TABLE_CITY ="virginia_dev_saayam_rdbms.city"
REAL_TABLE_USER_SKILLS ="virginia_dev_saayam_rdbms.user_skills"
REAL_TABLE_VOLUNTEER_LOCATIONS ="virginia_dev_saayam_rdbms.volunteer_locations"
REAL_TABLE_USER_LOCATIONS ="virginia_dev_saayam_rdbms.user_locations"
REAL_TABLE_COUNTRY ="virginia_dev_saayam_rdbms.country"
REAL_TABLE_HELP_CATEGORIES = "virginia_dev_saayam_rdbms.help_categories"

def lambda_handler(event, context):
    conn = None
    cursor = None

    safe_response = {
        "volunteer_activity_trend":{
        "new_volunteers": [],
        "active_volunteers": [],
        "total_volunteers": []}
    }
    DB_CONFIG = {
        "host": os.environ['host'],
        "port": os.environ['port'],
        "dbname": os.environ['dbname'],
        "user": os.environ['user'],
        "password": os.environ['password']
    }
    try:
        # Connects to database
        conn = psycopg2.connect(**DB_CONFIG)
        cursor = conn.cursor()
        print ("Successfully connected to the databases")

        country = event.get("country", "All Countries")
        chart_type = event.get("chart_type", "Bar Chart")
        skill = event.get("skill", "All Skills")

        response_data = {
             "volunteer_activity_trend": get_volunteer_activity_trend(cursor),
             "volunteers_by_location": get_volunteers_by_location(cursor, 
            country, 
            chart_type, 
            skill)
        }

        return {
            "statusCode": 200,
            "body": json.dumps(response_data)
        }
    except Exception as e:
        # Catches an error if connection fails
        print("ERROR:", str(e))
        return {
            'statusCode': 500,
            'body': json.dumps(safe_response)
        }
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()
        print("Database connection closed")

   


def get_volunteer_activity_trend(cursor):
    try: 
        query1 = f"""SELECT TO_CHAR(DATE_TRUNC('month', vd.created_at), 'YYYY-MM') AS month,
        COUNT(DISTINCT u.user_id) AS count 
        FROM {REAL_TABLE_USERS} u 
        JOIN {REAL_TABLE_VOLUNTEER_DETAILS} vd ON u.user_id = vd.user_id 
        WHERE vd.created_at IS NOT NULL 
        GROUP BY 1 
        ORDER BY 1 ASC"""
        cursor.execute(query1)

    
        new_volunteers = cursor.fetchall()
        new_volunteers_final = [{"month": row[0], "count": int(row[1])} for row in new_volunteers]

        query2 = f""" 
        SELECT TO_CHAR(DATE_TRUNC('month', vd.created_at), 'YYYY-MM') AS month,
        COUNT(DISTINCT u.user_id) AS count FROM {REAL_TABLE_USERS} u 
        JOIN {REAL_TABLE_VOLUNTEER_DETAILS} vd ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        AND u.user_status_id = 1 
        GROUP BY 1
        ORDER BY 1 ASC
        """
        cursor.execute(query2)
        active_volunteers = cursor.fetchall()
        active_volunteers_final = [{"month": row[0], "count": int(row[1])} for row in active_volunteers]

        query3 = f"""
        SELECT month, SUM(count) OVER (ORDER BY month) AS count
        FROM ( SELECT TO_CHAR(DATE_TRUNC('month', vd.created_at), 'YYYY-MM') AS month,
        COUNT(DISTINCT u.user_id) AS count
        FROM {REAL_TABLE_USERS} u
        JOIN {REAL_TABLE_VOLUNTEER_DETAILS} vd
        ON u.user_id = vd.user_id
        WHERE vd.created_at IS NOT NULL
        GROUP BY 1 ) sub
        ORDER BY month ASC;
        """
        
        cursor.execute(query3)
        total_volunteers = cursor.fetchall()
        total_volunteers_final = [{"month": row[0], "count": int(row[1])} for row in total_volunteers]
        return {
            "new_volunteers": new_volunteers_final,
            "active_volunteers": active_volunteers_final,
            "total_volunteers": total_volunteers_final
}

    except Exception as e:
        print("Error in get_volunteer_activity_trend:", str(e))
        return {
            "new_volunteers": [],
            "active_volunteers": [],
            "total_volunteers": []
        }

def get_volunteers_by_location(cursor, country='All Countries', chart_type="Bar Chart",skill="All Skills"):
    try: 
        query= f"""SELECT
                COALESCE(c.country_name, 'Unknown') AS country,
                COUNT(DISTINCT u.user_id) AS count
            FROM {REAL_TABLE_USERS} u
            JOIN {REAL_TABLE_VOLUNTEER_DETAILS} vd
                ON u.user_id = vd.user_id
            LEFT JOIN {REAL_TABLE_COUNTRY} c
                ON u.country_id = c.country_id
            LEFT JOIN {REAL_TABLE_STATE} s 
            ON u.state_id = s.state_id
            WHERE 1=1
            """
        
        params = []

        
        if country != "All Countries":
            query += " AND c.country_name = %s"
            params.append(country)

        if skill != 'All Skills':
            query += f""" 
            AND EXISTS (SELECT 1 
            FROM {REAL_TABLE_USER_SKILLS} us JOIN
            {REAL_TABLE_HELP_CATEGORIES} h ON 
            us.cat_id = h.cat_id 
            WHERE us.user_id = u.user_id 
            AND h.cat_name = %s)""" 
            params.append(skill)
        
        query += """
            GROUP BY COALESCE(c.country_name, 'Unknown')
            ORDER BY count DESC;
        """


        cursor.execute(query, params)
        rows = cursor.fetchall()

        return [
            {"country": row[0], "count": int(row[1])}
            for row in rows
        ]

    except Exception as e:
        print("Error in get_volunteers_by_location:", str(e))
        return []

    
if __name__ == "__main__":
    test_event = {"skill":"COOKING_HELP"}
    print(lambda_handler(test_event, None))
    


  
