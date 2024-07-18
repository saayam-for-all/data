from flask import Flask, jsonify, request
from fraud_detection import is_fraudulent_request

app = Flask(__name__)

@app.route('/api/check_fraud', methods=['POST'])
def check_fraud():
    #
    data = request.json
    user_id = data.get('user_id')
    request_location = data.get('location')
    request_count = data.get('request_count', 0)

    is_fraud, reason = is_fraudulent_request(user_id, request_location, request_count)

    response = {
        "is_fraud": is_fraud,
        "reason": reason
    }
    return jsonify(response), 200

# Run the application
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
