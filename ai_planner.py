import os
import json
import re
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from db import get_db_connection

load_dotenv()

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

def get_menu_items():
    """Fetch current menu items from the database."""
    conn = get_db_connection()
    if not conn:
        return []
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT id, name, price, description, category, health, 
               calories, protein, carbs, fats, rating, tags 
        FROM menu
        ORDER BY category, price
    """)
    items = cursor.fetchall()
    cursor.close()
    conn.close()
    
    # Format float prices for JSON serialization
    for item in items:
        item['price'] = float(item['price'])
        item['rating'] = float(item['rating']) if item['rating'] else 4.5
        item['health'] = (item['health'] or 'green').lower()
    return items

def calculate_plan_metrics(days_plan, menu_dict, budget=None):
    """
    Computes exact database-verified metrics for the AI-planned meals.
    """
    total_cost = 0.0
    total_calories = 0
    total_protein = 0
    total_carbs = 0
    total_fats = 0
    health_points = 0.0
    verified_days = []
    
    seen_ids = set()
    variety_count = 0
    num_days = max(1, len(days_plan))
    pts_per_green = 100.0 / num_days
    pts_per_amber = 0.70 * pts_per_green
    pts_per_red = 0.35 * pts_per_green

    for day_info in days_plan:
        day_name = day_info.get("day", "Day")
        item_id = day_info.get("item_id")
        
        # Look up item in menu_dict
        item = menu_dict.get(item_id)
        if not item:
            name = day_info.get("name", "").strip().lower()
            for m in menu_dict.values():
                if m["name"].strip().lower() == name:
                    item = m
                    break
        
        if not item:
            continue

        item_price = float(item["price"])
        total_cost += item_price
        total_calories += int(item.get("calories") or 0)
        total_protein += int(item.get("protein") or 0)
        total_carbs += int(item.get("carbs") or 0)
        total_fats += int(item.get("fats") or 0)

        h = (item.get("health") or "green").lower()
        if "green" in h:
            health_points += pts_per_green
        elif "amber" in h:
            health_points += pts_per_amber
        else:
            health_points += pts_per_red

        if item["id"] not in seen_ids:
            seen_ids.add(item["id"])
            variety_count += 1

        verified_days.append({
            "day": day_name,
            "item_id": item["id"],
            "name": item["name"],
            "price": item_price,
            "health": item["health"],
            "calories": item.get("calories") or 0,
            "protein": item.get("protein") or 0,
            "carbs": item.get("carbs") or 0,
            "fats": item.get("fats") or 0,
            "rating": item.get("rating") or 4.5,
            "category": item.get("category") or "",
            "reason": day_info.get("reason", "Personalized choice based on your preferences.")
        })

    # Variety bonus (up to 5 points)
    if variety_count >= min(4, num_days):
        health_points = min(100.0, health_points + 5.0)
    
    weekly_health_score = max(10, min(100, round(health_points)))
    
    # Grade determination
    if weekly_health_score >= 85:
        grade = "A+ (Excellent)"
    elif weekly_health_score >= 75:
        grade = "A (Very Healthy)"
    elif weekly_health_score >= 60:
        grade = "B (Balanced)"
    else:
        grade = "C (Needs Improvement)"

    remaining_budget = None
    if budget is not None:
        remaining_budget = round(budget - total_cost, 2)

    return {
        "days": verified_days,
        "total_cost": round(total_cost, 2),
        "budget": budget,
        "remaining_budget": remaining_budget,
        "is_within_budget": (total_cost <= budget) if budget is not None else True,
        "total_calories": total_calories,
        "total_protein": total_protein,
        "total_carbs": total_carbs,
        "total_fats": total_fats,
        "avg_daily_calories": round(total_calories / max(1, len(verified_days))),
        "avg_daily_protein": round(total_protein / max(1, len(verified_days)), 1),
        "avg_daily_carbs": round(total_carbs / max(1, len(verified_days)), 1),
        "avg_daily_fats": round(total_fats / max(1, len(verified_days)), 1),
        "weekly_health_score": weekly_health_score,
        "grade": grade
    }

def generate_meal_plan(user_message, budget=None, conversation_history=None):
    """
    Calls Gemini AI to dynamically reason, plan, and choose a personalized 5-day meal plan
    (Monday to Friday) strictly within the user's budget using items from the canteen menu.
    """
    menu_items = get_menu_items()
    menu_dict = {item['id']: item for item in menu_items}

    # Extract budget from message if not provided explicitly
    if budget is None:
        budget_match = re.search(r'(?:budget\s*(?:is|of|:)?\s*₹?\s*|₹\s*|rs\.?\s*|inr\s*)(\d{2,5})', user_message, re.IGNORECASE)
        if budget_match:
            try:
                budget = float(budget_match.group(1))
            except ValueError:
                pass

    menu_catalog = []
    for m in menu_items:
        menu_catalog.append({
            "id": m["id"],
            "name": m["name"],
            "price": m["price"],
            "health": m["health"],
            "calories": m["calories"],
            "protein_g": m["protein"],
            "carbs_g": m["carbs"],
            "fats_g": m["fats"],
            "category": m["category"],
            "tags": m.get("tags") or ""
        })

    system_instruction = f"""
You are "Compass AI", an expert AI canteen nutritionist and meal planner for Cafeteria Compass.
Your objective is to intelligently analyze the user's request and craft a personalized 5-day meal plan (Monday to Friday only) using the live canteen menu catalog provided below.

CRITICAL INSTRUCTIONS FOR AI PLANNING:
1. PURE AI PLANNING:
   - Do NOT use hardcoded templates or canned responses.
   - You must actively read the user's preferences (e.g. dietary restrictions, high protein, vegetarian, favorite dishes, light lunch, etc.) and tailor the 5 dishes specifically to them.
2. 5 DAYS ONLY (MONDAY TO FRIDAY):
   - The plan must have exactly 5 days: Monday, Tuesday, Wednesday, Thursday, Friday.
   - Do NOT include Saturday or Sunday.
   - Each day must have exactly 1 food item (total 5 items for the week).
3. MENU ITEMS ONLY:
   - Every single dish MUST be selected from the Official Canteen Menu Catalog below. Use its exact "id" and "name".
   - Do not invent new dishes.
4. STRICT BUDGET LIMIT:
   - Weekly budget limit: ₹{budget if budget else "specified by user"}.
   - The sum of the prices of all 5 chosen dishes MUST be LESS THAN OR EQUAL TO the budget.
   - Verify your mathematical calculation before finalizing the plan.
5. HEALTH & NUTRITION:
   - Provide your genuine AI reasoning for each day's selection based on the user's prompt.
   - Provide 2-3 tailored nutrition tips.
6. RESPONSE FORMAT:
   Return valid JSON with this structure:
   {{
     "message": "<Your personalized, friendly conversational response explaining your plan to the user>",
     "budget": {budget if budget else "null"},
     "plan": [
       {{
         "day": "Monday",
         "item_id": 0,
         "name": "string",
         "reason": "string"
       }},
       {{
         "day": "Tuesday",
         "item_id": 0,
         "name": "string",
         "reason": "string"
       }},
       {{
         "day": "Wednesday",
         "item_id": 0,
         "name": "string",
         "reason": "string"
       }},
       {{
         "day": "Thursday",
         "item_id": 0,
         "name": "string",
         "reason": "string"
       }},
       {{
         "day": "Friday",
         "item_id": 0,
         "name": "string",
         "reason": "string"
       }}
     ],
     "health_tips": [
       "<tip 1>",
       "<tip 2>"
     ]
   }}

Do not include markdown fences like ```json. Return raw JSON only.

OFFICIAL CANTEEN MENU CATALOG:
{json.dumps(menu_catalog, indent=2)}
"""

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"User Request: {user_message}\n"
    prompt += "Please plan meals for 5 days: Monday, Tuesday, Wednesday, Thursday, Friday (1 item per day).\n"
    if budget:
        prompt += f"Weekly Budget: ₹{budget} (Strict maximum total for all 5 days <= ₹{budget})\n"

    if conversation_history and len(conversation_history) > 0:
        history_context = "Previous Conversation:\n"
        for msg in conversation_history[-6:]:
            history_context += f"{msg.get('role', 'user').capitalize()}: {msg.get('content', '')}\n"
        prompt = history_context + "\n" + prompt

    parsed_json = None
    last_error = None

    # Retry loop with backoff for API resilience
    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    temperature=0.4,
                    response_mime_type="application/json"
                )
            )
            response_text = response.text.strip()
            # Clean possible markdown wrap
            cleaned = re.sub(r'^```json\s*', '', response_text)
            cleaned = re.sub(r'```$', '', cleaned).strip()
            parsed_json = json.loads(cleaned)
            if parsed_json and "plan" in parsed_json and len(parsed_json["plan"]) >= 5:
                break
        except Exception as e:
            last_error = e
            time.sleep(1.0 * (attempt + 1))

    if not parsed_json or "plan" not in parsed_json or len(parsed_json["plan"]) < 5:
        raise RuntimeError(f"Gemini AI was unable to generate the meal plan: {last_error}")

    valid_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    raw_days = [d for d in parsed_json.get("plan", []) if d.get("day") in valid_days][:5]

    plan_metrics = calculate_plan_metrics(raw_days, menu_dict, budget)

    return {
        "success": True,
        "message": parsed_json.get("message", "Here is your 5-day meal plan from Monday to Friday tailored specifically to your request and budget!"),
        "health_tips": parsed_json.get("health_tips", [
            "Balanced meals with green choices help maintain consistent energy levels for study and work.",
            "Stay hydrated alongside your daily canteen meal."
        ]),
        "plan_metrics": plan_metrics
    }
