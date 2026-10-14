from flask import Flask, jsonify, request
from src.extensions import db
from datetime import datetime, timedelta
from src.models.fraud_requests import FraudRequests
from src import config
from src.profanity import (
    InvalidSeverityScoreError,
    ProfanityApiError,
    evaluate_help_request,
)
from src.translation.lang_detection import translate_to_english

app = Flask(__name__)

app.config.from_object(config)
db.init_app(app)

with app.app_context():
        db.create_all()

@app.route('/')
def home():
     return jsonify('Service is running')

@app.route('/api/check_fraud', methods=['POST'])
def check_fraud():
    data = request.json
    user_id = data.get('user_id')
    request_datetime = data.get('request_date')
    request_datetime = datetime.strptime(request_datetime, '%Y-%m-%d %H:%M:%S')

    # Calculate the time window (30 minutes before the request datetime)
    time_window_start = request_datetime - timedelta(minutes=30)

    # Query the database using raw SQL
    query = """
        SELECT COUNT(*)
        FROM proposed_saayam.request
        WHERE request_user_id = :user_id
        AND submission_date BETWEEN :time_window_start AND :request_datetime
    """
    result = db.session.execute(
        db.text(query),
        {
            'user_id': user_id,
            'time_window_start': time_window_start,
            'request_datetime': request_datetime
        }
    ).scalar()
    is_fraud=False
    reason="Request is Valid"
    # Check if any request exists in the past 30 minutes
    if result > 0:
        is_fraud=True
        reason="Already requested within last 30 mins"

        fraud_request = FraudRequests(
            user_id=user_id,
            request_datetime=request_datetime,
            reason=reason
        )
        db.session.add(fraud_request)
        db.session.commit()

    response = {
        "is_fraud": is_fraud,
        "reason": reason
    }
    return jsonify(response), 200


# New API for the Help Request workflow (Issue #422): evaluate profanity/severity score
# and route requests to active matching (score 0) or fraud_requests (scores 1-3).
@app.route('/api/check_profanity', methods=['POST'])
def check_profanity():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "A JSON object body is required"}), 400

    user_id = data.get('user_id')
    if user_id is None:
        return jsonify({"error": "user_id is required"}), 400
    if isinstance(user_id, bool) or not isinstance(user_id, (str, int)):
        return jsonify({"error": "user_id must be a string or integer"}), 400
    user_id_str = str(user_id).strip()
    if not user_id_str:
        return jsonify({"error": "user_id must not be empty"}), 400

    try:
        result = evaluate_help_request(data)
    except ProfanityApiError:
        app.logger.exception("Profanity API call failed for /api/check_profanity")
        return jsonify({"error": "Unable to classify the request at this time"}), 502
    except (ValueError, InvalidSeverityScoreError) as error:
        return jsonify({"error": str(error)}), 400

    if result["is_flagged"]:
        try:
            request_datetime_raw = data.get('request_date') or data.get('request_datetime')
            request_datetime = datetime.now()
            if request_datetime_raw and isinstance(request_datetime_raw, str):
                try:
                    request_datetime = datetime.strptime(request_datetime_raw, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    try:
                        request_datetime = datetime.fromisoformat(request_datetime_raw)
                    except ValueError:
                        request_datetime = datetime.now()

            fraud_request = FraudRequests(
                user_id=user_id_str,
                request_datetime=request_datetime,
                reason=result["reason"]
            )
            db.session.add(fraud_request)
            db.session.commit()
        except Exception:
            db.session.rollback()
            app.logger.exception("Could not record flagged request for /api/check_profanity")
            return jsonify({"error": "Unable to record the flagged request"}), 500

    response = {
        "is_flagged": result["is_flagged"],
        "severity_score": result["severity_score"],
        "reason": result["reason"],
        "destination": result["destination"],
        "database_table": result["database_table"],
        "action": result["action"],
        "allow_active_matching": result["allow_active_matching"],
        "flagged_categories": result.get("flagged_categories", []),
    }
    return jsonify(response), 200


# New API for language detection and translation
@app.route('/api/translate', methods=['POST'])
def translate_request_content():
    data = request.get_json()
    content = data.get('content', '')

    if not content:
        return jsonify({"error": "No content provided"}), 400

    # Translate the text to English
    translated_content = translate_to_english(content)
    
    response = {
        "original": content,
        "translated": translated_content
    }
    return jsonify(response), 200

# Run the application
if __name__ in "main":
    app.run(debug=True)
