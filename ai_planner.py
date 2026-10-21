import os
import json
import re
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
    Programmatically calculates and verifies metrics for the 5-day meal plan (Monday to Friday)
    using exact database values to guarantee strict budget adherence and accurate nutrition.
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
            # Try finding by name if item_id doesn't match
            name = day_info.get("name", "").strip().lower()
            for m in menu_dict.values():
                if m["name"].strip().lower() == name:
                    item = m
                    break
        
        if not item:
            # Fallback to cheapest green item if missing
            item = next((m for m in menu_dict.values() if 'green' in m['health']), list(menu_dict.values())[0])

        item_price = float(item["price"])
        total_cost += item_price
        total_calories += int(item.get("calories") or 0)
        total_protein += int(item.get("protein") or 0)
        total_carbs += int(item.get("carbs") or 0)
        total_fats += int(item.get("fats") or 0)

        # Health score calculation per meal:
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
            "reason": day_info.get("reason", "Great nutritional balance")
        })

    # Add variety bonus (up to 5 points if high variety)
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

def enforce_strict_budget(plan_metrics, menu_items, budget):
    """
    If the AI plan accidentally exceeded the budget, replace higher-priced items
    with nutritious lower-priced items from the menu until total_cost <= budget.
    """
    if budget is None or plan_metrics["total_cost"] <= budget:
        return plan_metrics
    
    menu_dict = {m["id"]: m for m in menu_items}
    # Sort candidate substitutes by price ascending
    cheaper_green_items = sorted(
        [m for m in menu_items if "green" in m["health"]], 
        key=lambda x: x["price"]
    )
    if not cheaper_green_items:
        cheaper_green_items = sorted(menu_items, key=lambda x: x["price"])
        
    days = list(plan_metrics["days"])
    
    # Iterate from most expensive day down
    attempts = 0
    while attempts < 20 and sum(d["price"] for d in days) > budget:
        attempts += 1
        # Find day with highest price
        highest_day_idx = max(range(len(days)), key=lambda i: days[i]["price"])
        current_item = days[highest_day_idx]
        
        # Pick a cheaper alternative that is different
        cheaper = next((sub for sub in cheaper_green_items if sub["price"] < current_item["price"]), None)
        if not cheaper:
            break
            
        days[highest_day_idx] = {
            "day": current_item["day"],
            "item_id": cheaper["id"],
            "name": cheaper["name"],
            "price": float(cheaper["price"]),
            "health": cheaper["health"],
            "calories": cheaper.get("calories") or 0,
            "protein": cheaper.get("protein") or 0,
            "carbs": cheaper.get("carbs") or 0,
            "fats": cheaper.get("fats") or 0,
            "rating": cheaper.get("rating") or 4.5,
            "category": cheaper.get("category") or "",
            "reason": f"Adjusted to strictly stay within your ₹{budget} weekly budget while keeping healthy greens."
        }

    return calculate_plan_metrics(days, menu_dict, budget)

def generate_meal_plan(user_message, budget=None, conversation_history=None):
    """
    Calls Gemini API to generate a personalized conversational weekly meal plan
    with exactly one food item per day, strictly within budget, drawing from canteen menu items.
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

    # Simplified menu summary for LLM prompt
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
            "category": m["category"]
        })

    system_instruction = f"""
You are "Compass AI", an expert canteen nutritionist and meal planner for Cafeteria Compass.
Your task is to converse with the user and provide a 5-day weekly meal plan (Monday to Friday only) based on the canteen's official menu.

CRITICAL RULES:
1. ONLY USE MENU ITEMS: Every recommended dish MUST be chosen from the provided menu catalog. Use its exact 'id' and 'name'.
2. EXACTLY ONE FOOD ITEM PER DAY (5 DAYS ONLY: MONDAY TO FRIDAY):
   - The plan covers ONLY 5 days: Monday, Tuesday, Wednesday, Thursday, Friday.
   - Strictly DO NOT include Saturday or Sunday.
   - Each day has EXACTLY ONE meal item (total 5 items).
   - Do NOT provide separate breakfast, lunch, or dinner. Just 1 item per day.
3. STRICT BUDGET LIMIT: The total cost of the 5 items MUST BE LESS THAN OR EQUAL TO the user's weekly budget (in ₹).
   - If budget is specified as ₹{budget or 'unspecified'}, the sum of the 5 meal prices MUST NOT EXCEED ₹{budget or 'user budget'}.
   - Choose healthy, budget-friendly items if the budget is modest.
4. USER PREFERENCES: Carefully consider the user's prompt (e.g., veg/non-veg, high protein, low calorie, light foods, specific cravings).
5. NUTRITIONAL VALUES & HEALTH SCORE:
   - Provide each item's calories, protein (g), carbs (g), fats (g), and health choice (Green/Amber/Red).
   - Evaluate a Weekly Health Score (out of 100) and grade (e.g., A+, A, B) based on nutritional balance, proportion of Green Choices, and protein intake.
6. RESPONSE FORMAT:
   You must respond in JSON format matching this schema:
   {{
     "message": "Friendly, encouraging conversational explanation of why this 5-day (Mon-Fri) plan fits the user's prompt and budget.",
     "budget": {budget if budget else "null"},
     "plan": [
       {{
         "day": "Monday",
         "item_id": 1,
         "name": "Masala Dosa",
         "reason": "Why this dish was selected for Monday"
       }},
       {{
         "day": "Tuesday",
         "item_id": 2,
         "name": "Paneer Butter Masala Meal",
         "reason": "Why this dish was selected for Tuesday"
       }},
       {{
         "day": "Wednesday",
         "item_id": 4,
         "name": "Veg Steamed Momos (6 pcs)",
         "reason": "Why this dish was selected for Wednesday"
       }},
       {{
         "day": "Thursday",
         "item_id": 9,
         "name": "Paneer Tikka Roll",
         "reason": "Why this dish was selected for Thursday"
       }},
       {{
         "day": "Friday",
         "item_id": 21,
         "name": "Student Executive Thali",
         "reason": "Why this dish was selected for Friday"
       }}
     ],
     "health_tips": [
       "Helpful tip 1 based on their plan",
       "Helpful tip 2"
     ]
   }}

Do not output markdown code fences like ```json. Output raw JSON only.

OFFICIAL CANTEEN MENU CATALOG:
{json.dumps(menu_catalog, indent=2)}
"""

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = f"User Request: {user_message}\n"
    prompt += "Requirement: Only 5 days from Monday to Friday (Monday, Tuesday, Wednesday, Thursday, Friday). Exactly one food item per day. Do NOT include Saturday or Sunday.\n"
    if budget:
        prompt += f"Weekly Budget: ₹{budget} (Strict maximum for 5 days Mon-Fri, sum of 5 items must be <= ₹{budget})\n"

    # Add conversation history context if provided
    history_context = ""
    if conversation_history and len(conversation_history) > 0:
        history_context = "Previous Conversation:\n"
        for msg in conversation_history[-6:]:
            history_context += f"{msg.get('role', 'user').capitalize()}: {msg.get('content', '')}\n"
        prompt = history_context + "\n" + prompt

    response_text = ""
    parsed_json = None

    try:
        response = client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=0.3,
                response_mime_type="application/json"
            )
        )
        response_text = response.text.strip()
        parsed_json = json.loads(response_text)
    except Exception as e:
        print(f"Gemini API error: {e}")
        try:
            cleaned = re.sub(r'^```json\s*', '', response_text)
            cleaned = re.sub(r'```$', '', cleaned).strip()
            parsed_json = json.loads(cleaned)
        except Exception:
            parsed_json = None



    # If parsing failed or no plan was returned, generate a smart fallback plan from menu items
    if not parsed_json or "plan" not in parsed_json or len(parsed_json["plan"]) < 5:
        parsed_json = create_rule_based_plan(user_message, budget, menu_items)

    # Extract days plan from response (ensure only Monday to Friday, max 5 days)
    valid_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
    raw_days = [d for d in parsed_json.get("plan", []) if d.get("day") in valid_days][:5]
    if len(raw_days) < 5:
        raw_days = create_rule_based_plan(user_message, budget, menu_items)["plan"]
    
    # Calculate exact database metrics
    plan_metrics = calculate_plan_metrics(raw_days, menu_dict, budget)

    # Strictly enforce budget limit
    if budget is not None and plan_metrics["total_cost"] > budget:
        plan_metrics = enforce_strict_budget(plan_metrics, menu_items, budget)

    return {
        "success": True,
        "message": parsed_json.get("message", "Here is your personalized 5-day canteen meal plan (Monday to Friday) tailored to your budget and preferences!"),
        "health_tips": parsed_json.get("health_tips", [
            "Opt for Green Choice items for steady energy throughout the work & study week.",
            "Stay hydrated alongside your daily canteen meal."
        ]),
        "plan_metrics": plan_metrics
    }

def create_rule_based_plan(user_message, budget, menu_items):
    """Fallback generator to construct a 5-day plan (Monday to Friday) strictly within budget."""
    is_veg_only = "veg" in user_message.lower() and "non-veg" not in user_message.lower()
    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]

    filtered_items = menu_items
    if is_veg_only:
        filtered_items = [m for m in menu_items if "veg" in (m.get("tags") or "").lower() and "non-veg" not in (m.get("tags") or "").lower()]

    if not filtered_items:
        filtered_items = menu_items

    # Sort primarily by health (green first) and price
    green_items = [m for m in filtered_items if "green" in m["health"]]
    pool = green_items if green_items else filtered_items

    max_daily_budget = (budget / 5.0) if budget else 100.0
    affordable_pool = [m for m in pool if m["price"] <= max_daily_budget * 1.3]
    if not affordable_pool:
        affordable_pool = sorted(filtered_items, key=lambda x: x["price"])[:5]

    plan = []
    for i, day in enumerate(days):
        selected = affordable_pool[i % len(affordable_pool)]
        plan.append({
            "day": day,
            "item_id": selected["id"],
            "name": selected["name"],
            "reason": f"Nutritious {selected['health'].capitalize()} Choice packed with {selected.get('protein', 0)}g protein."
        })

    return {
        "message": f"I've tailored a balanced 5-day meal plan (Monday to Friday) strictly staying within your weekly budget of ₹{budget or 'the canteen standards'}, with one healthy item per day.",
        "budget": budget,
        "plan": plan,
        "health_tips": [
            "Balanced meals with green choices help maintain consistent energy levels for study and work.",
            "Pair these with plenty of water for optimal nutrition."
        ]
    }

