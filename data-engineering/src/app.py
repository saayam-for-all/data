from flask import Flask, jsonify, request
from src.extensions import db
from datetime import datetime, timedelta
from src.models.fraud_requests import FraudRequests
from src.profanity import (
    ProfanityAPIError,
    call_profanity_api,
    get_routing_decision,
)
from src import config
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
@app.route('/api/check_profanity', methods=['POST'])
def check_profanity():
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        return jsonify({
            "error": "A JSON request body is required."
        }), 400

    user_id = data.get("user_id")
    subject = data.get("subject")
    description = data.get("description")

    if not isinstance(user_id, str) or not user_id.strip():
        return jsonify({
            "error": "user_id must be a non-empty string."
        }), 400

    if not isinstance(subject, str) or not subject.strip():
        return jsonify({
            "error": "subject must be a non-empty string."
        }), 400

    if (
        not isinstance(description, str)
        or not description.strip()
    ):
        return jsonify({
            "error": "description must be a non-empty string."
        }), 400

    try:
        score = call_profanity_api(subject, description)
        decision = get_routing_decision(score)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except ProfanityAPIError as exc:
        return jsonify({"error": str(exc)}), 502

    if decision["is_flagged"]:
        fraud_request = FraudRequests(
            user_id=user_id.strip(),
            reason=(
                f"{decision['reason']} "
                f"(severity {decision['severity_score']})"
            ),
        )
        db.session.add(fraud_request)
        db.session.commit()

    return jsonify(decision), 200


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
