from flask import Flask, request, jsonify
import uuid
import random
import statistics
from collections import Counter
import math

app = Flask(__name__)

# In-memory store for challenges. In production, use a database.
# challenges_data = {
# "secret_key_example": {
# "email": "user@example.com",
# "numbers_y": [10, 20, 15, 20, 25],
# "correct_stats": {
# "count": 5,
# "minimum": 10,
# "maximum": 25,
# "mean": 18.0,
# "median": 20,
# "mode": 20 # or a list of modes if multiple exist
#       },
# "step2_attempts": 0,
# "last_correct_submission": None # Stores the body of the last successful step2
#   }
# }
challenges_data = {}
MAX_STEP2_ATTEMPTS = 10

# --- Helper Function to Calculate Statistics ---
def calculate_statistics(numbers_y):
    if not numbers_y:
        return {
            "count": 0,
            "minimum": None,
            "maximum": None,
            "mean": None,
            "median": None,
            "mode": None, # Or an empty list for modes
        }

    count = len(numbers_y)
    minimum = min(numbers_y)
    maximum = max(numbers_y)
    mean = statistics.mean(numbers_y)
    median = statistics.median(numbers_y)

    # Mode calculation: handle multiple modes
    # We'll consider any of the most frequent numbers as a valid mode.
    counts = Counter(numbers_y)
    max_freq = max(counts.values())
    modes = sorted([num for num, freq in counts.items() if freq == max_freq]) # Get all modes, sorted
    
    # For this challenge, let's just store all possible modes.
    # The validation will check if the user's mode is IN this list.
    # If the challenge expects a single mode (e.g., the smallest), pick modes[0].
    # The prompt seems to imply a single mode value in the request, so
    # the validation will need to be flexible if multiple modes are possible.

    return {
        "count": count,
        "minimum": float(minimum),
        "maximum": float(maximum),
        "mean": float(mean),
        "median": float(median),
        "modes": [float(m) for m in modes], # Store all modes, client will send one
    }

# --- API Endpoints ---

@app.route('/challenge/step1', methods=['GET'])
def step1_get_challenge():
    email = request.args.get('email')
    if not email:
        return jsonify({"error": "Email parameter is required"}), 400

    secret_key = uuid.uuid4().hex
    # Generate a random list of numbers (Y)
    # For example, 5 to 15 numbers, ranging from 1 to 100
    num_elements = random.randint(5, 15)
    numbers_y = [random.randint(1, 100) for _ in range(num_elements)]

    correct_stats = calculate_statistics(numbers_y)

    challenges_data[secret_key] = {
        "email": email,
        "numbers_y": numbers_y,
        "correct_stats": correct_stats,
        "step2_attempts": 0,
        "last_correct_submission_data": None # To store the full valid payload
    }

    app.logger.info(f"Step 1 for {email}: secret_key={secret_key}, numbers={numbers_y}, stats={correct_stats}")

    return jsonify({
        "secret_key": secret_key,
        "numbers": numbers_y
    }), 200

@app.route('/challenge/step2', methods=['POST'])
def step2_submit_statistics():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"message": "Please try again!!! (Invalid JSON)"}), 400

        secret_key = data.get('secret_key')
        user_stats = {
            "count": data.get('count'),
            "minimum": data.get('minimum'),
            "maximum": data.get('maximum'),
            "mean": data.get('mean'),
            "median": data.get('median'),
            "mode": data.get('mode')
        }
    except Exception as e:
        app.logger.error(f"Error parsing Step 2 request: {e}")
        return jsonify({"message": "Please try again!!! (Malformed request)"}), 400

    if not secret_key or not all(user_stats[k] is not None for k in user_stats): # Check if all stat keys are present
        return jsonify({"message": "Please try again!!! (Missing fields)"}), 400

    challenge_info = challenges_data.get(secret_key)

    if not challenge_info:
        return jsonify({"message": "Please try again!!! (Invalid secret_key)"}), 400

    # Rate Limiting
    if challenge_info["step2_attempts"] >= MAX_STEP2_ATTEMPTS:
        # If a correct submission was already made, they still get the success message for that.
        # The "last correct attempt" rule implies that even if they hit the limit, if one was correct, it counts.
        # However, if they hit the limit *without* a correct submission, it's a hard fail.
        if challenge_info["last_correct_submission_data"]:
             return jsonify({"message": "Your response has been submitted successfully", "note": "Rate limit reached, but previous submission was correct."}), 200
        else:
            return jsonify({"message": "Please try again!!! (Max attempts reached)"}), 429 # Too Many Requests

    challenge_info["step2_attempts"] += 1
    app.logger.info(f"Step 2 attempt {challenge_info['step2_attempts']}/{MAX_STEP2_ATTEMPTS} for secret_key={secret_key}")


    correct_stats = challenge_info["correct_stats"]
    
    # Validation
    valid_submission = True
    errors = []

    if user_stats["count"] != correct_stats["count"]:
        valid_submission = False
        errors.append(f"Count mismatch: expected {correct_stats['count']}, got {user_stats['count']}")
    
    # Use math.isclose for float comparisons
    if not math.isclose(float(user_stats["minimum"]), correct_stats["minimum"]):
        valid_submission = False
        errors.append(f"Minimum mismatch: expected {correct_stats['minimum']}, got {user_stats['minimum']}")
    
    if not math.isclose(float(user_stats["maximum"]), correct_stats["maximum"]):
        valid_submission = False
        errors.append(f"Maximum mismatch: expected {correct_stats['maximum']}, got {user_stats['maximum']}")
        
    if not math.isclose(float(user_stats["mean"]), correct_stats["mean"], rel_tol=1e-9, abs_tol=1e-9):
        valid_submission = False
        errors.append(f"Mean mismatch: expected {correct_stats['mean']:.2f}, got {user_stats['mean']:.2f}") # Format for logging
        
    if not math.isclose(float(user_stats["median"]), correct_stats["median"], rel_tol=1e-9, abs_tol=1e-9):
        valid_submission = False
        errors.append(f"Median mismatch: expected {correct_stats['median']}, got {user_stats['median']}")

    # Mode validation: check if user's mode is one of the correct modes
    if float(user_stats["mode"]) not in correct_stats["modes"]:
        valid_submission = False
        errors.append(f"Mode mismatch: expected one of {correct_stats['modes']}, got {user_stats['mode']}")


    if valid_submission:
        # "In case of multiple attempts, the last correct attempt would be considered as your final submission."
        challenge_info["last_correct_submission_data"] = data # Store the successful payload
        app.logger.info(f"Step 2 SUCCESS for secret_key={secret_key}. Data: {data}")
        return jsonify({"message": "Your response has been submitted successfully"}), 200
    else:
        app.logger.warning(f"Step 2 FAIL for secret_key={secret_key}. User stats: {user_stats}, Errors: {errors}")
        # Even if it fails, if there was a *previous* correct submission within the attempts,
        # that one still stands as the "last correct attempt".
        # The current "Please try again!!!" message is for the current *failed* attempt.
        return jsonify({"message": "Please try again!!!"}), 400 # Bad Request for incorrect stats

if __name__ == '__main__':
    # Enable logging for development
    import logging
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, port=5001) # Running on a different port e.g. 5001