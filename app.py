import os
import json
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from db import get_db_connection
import mysql.connector
from dotenv import load_dotenv
from ai_planner import generate_meal_plan

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key')


@app.route('/')
def home():
    if 'user_id' in session and session.get('role') == 'Student':
        return redirect(url_for('menu'))
    elif 'user_id' in session and session.get('role') == 'Parent':
        return redirect(url_for('order_history'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        # Role is NOT asked at registration as per requirement? 
        # Wait, user said: "role based student/teacher and parent it should ask role only at the time of login not at time of registering the account"
        # This implies the user account itself doesn't have a fixed role? Or the role is selected during login?
        # If "ask role only at the time of login", then one account can be potentially anything?
        # OR, registration just creates a user, and they claim a role at login?
        # A bit ambiguous. Usually a user HAS a role.
        # "it should ask role only at the time of login not at time of registering" -> suggests the user picks "I am logging in as a Parent".
        # But surely the system needs to know if they ARE a parent?
        # Maybe the user means: "Simpler registration (just user/pass), and at login you say who you are."
        # If I register as "Arnav", do I choose my role then? User says "not at time of registering".
        # So I will just store username/password.
        # At login, they pick a role.
        # Does this mean I can login as Student one day and Parent another?
        # I'll implement it such that the `users` table might just store the credentials, and the session stores the role. 
        # OR, the `users` table *should* have a role, but it's assigned default or inferred?
        # Re-reading: "ask role only at the time of login not at time of registering values"
        # I'll follow this strictly: Registration = User/Pass. Login = User/Pass + Role.
        # If the DB schema *requires* a role (I put NOT NULL), I might need to adjust or set a default.
        # I'll update schema to remove role from `users` or make it nullable, 
        # OR I just don't check it against the DB role, just use the selected role for the session logic?
        # But if a Teacher logs in, they should see teacher stuff.
        # I will assume for this MVP that the Role is purely a session-context thing or we update the user's role on first login?
        # Let's simple store it in session.
        
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            # We'll insert with a default role or NULL if I change schema.
            # For now, let's just insert 'Student' as placeholder if schema enforces it, or remove column.
            # My created schema had `role` column.
            # I will modify schema to remove role if strictly following "not at registering".
            # Or I'll just set it to 'Student' by default.
            cursor.execute("INSERT INTO users (username, password_hash, role) VALUES (%s, %s, 'Student')", (username, password))
            conn.commit()
            flash('Registration successful! Please login.')
            return redirect(url_for('login'))
        except mysql.connector.Error as e:
            flash(f'Error: {e}')
        finally:
            cursor.close()
            conn.close()
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        role = request.form['role']
        
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s AND password_hash = %s", (username, password))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = role # Trust the user's selection for the session context
            
            if role == 'Parent':
                return redirect(url_for('order_history'))
            else:
                return redirect(url_for('menu'))
        else:
            flash('Invalid credentials')
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/menu')
def menu():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    
    query = request.args.get('q')
    if query:
        cursor.execute("SELECT * FROM menu WHERE name LIKE %s", (f"%{query}%",))
    else:
        cursor.execute("SELECT * FROM menu")
        
    items = cursor.fetchall()
    cursor.close()
    conn.close()
    return render_template('menu.html', items=items)

@app.route('/cart')
def cart():
    # Helper to view cart (client side storage or session?)
    # For a real app, maybe session or local storage. 
    # I'll implement a simple session-based cart or just render the page and let JS handle it.
    # User asked for "cart in which there should be two option vend reciept and place order"
    # So I'll render a cart template.
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('cart.html')

@app.route('/checkout', methods=['POST'])
def checkout():
    if 'user_id' not in session: 
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401

    data = request.get_json()
    order_type = data.get('type') # 'Vend Receipt' or 'Place Order'
    cart_items = data.get('items')
    
    if not cart_items:
        return jsonify({'success': False, 'message': 'Cart empty'}), 400

    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Cast to float/int to ensure correct calculation and types
        total = sum(float(item['price']) * int(item['quantity']) for item in cart_items)
        
        cursor.execute("INSERT INTO orders (user_id, total_amount, order_type, status) VALUES (%s, %s, %s, 'Pending')", 
                       (session['user_id'], total, order_type))
        order_id = cursor.lastrowid
        
        for item in cart_items:
            cursor.execute("INSERT INTO order_items (order_id, menu_id, quantity, price) VALUES (%s, %s, %s, %s)",
                           (order_id, item['id'], int(item['quantity']), float(item['price'])))
            
        conn.commit()
        return jsonify({'success': True, 'message': 'Order placed successfully!'})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route('/history')
def order_history():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT o.id, o.total_amount, o.order_type, o.status, o.created_at,
               GROUP_CONCAT(CONCAT(m.name, ' x', oi.quantity) SEPARATOR ', ') as ordered_items
        FROM orders o
        JOIN order_items oi ON o.id = oi.order_id
        JOIN menu m ON oi.menu_id = m.id
        WHERE o.user_id = %s
        GROUP BY o.id
        ORDER BY o.created_at DESC
    """, (session['user_id'],))
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return render_template('history.html', orders=orders)

@app.route('/api/history')
def api_history():
    if 'user_id' not in session: 
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
    
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT o.id, o.total_amount, o.order_type, o.status, o.created_at,
               GROUP_CONCAT(CONCAT(m.name, ' x', oi.quantity) SEPARATOR ', ') as ordered_items
        FROM orders o
        JOIN order_items oi ON o.id = oi.order_id
        JOIN menu m ON oi.menu_id = m.id
        WHERE o.user_id = %s
        GROUP BY o.id
        ORDER BY o.created_at DESC
    """, (session['user_id'],))
    orders = cursor.fetchall()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True, 'orders': orders})

# --- REVIEWS API ---
@app.route('/api/reviews', methods=['GET'])
def get_reviews():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM reviews ORDER BY created_at DESC")
    reviews = cursor.fetchall()
    conn.close()
    return jsonify({'success': True, 'reviews': reviews})

@app.route('/api/reviews', methods=['POST'])
def add_review():
    if 'user_id' not in session:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 401
        
    data = request.get_json()
    rating = data.get('rating')
    comment = data.get('comment')
    
    if not rating or not comment:
         return jsonify({'success': False, 'message': 'Missing data'}), 400
         
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO reviews (user_id, username, rating, comment) VALUES (%s, %s, %s, %s)",
                   (session['user_id'], session['username'], rating, comment))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Review added!'})

# --- AI MEAL PLANNER CHATBOT API ---
@app.route('/api/chatbot', methods=['POST'])
def api_chatbot():
    data = request.get_json() or {}
    message = data.get('message', '').strip()
    budget = data.get('budget')
    history = data.get('history', [])

    if not message and budget is None:
        return jsonify({'success': False, 'message': 'Please enter a message or a weekly budget.'}), 400

    try:
        if budget is not None and str(budget).strip() != '':
            budget = float(budget)
        else:
            budget = None
    except (ValueError, TypeError):
        budget = None

    try:
        result = generate_meal_plan(
            user_message=message or f"Please create a 5-day meal plan (Monday to Friday) for a weekly budget of ₹{budget}",
            budget=budget,
            conversation_history=history
        )
        
        # Save generated weekly plan to MySQL if user is logged in
        user_id = session.get('user_id')
        if user_id and result.get('success') and result.get('plan_metrics'):
            try:
                metrics = result['plan_metrics']
                plan_json_str = json.dumps(result)
                db = get_db_connection()
                if db:
                    cursor = db.cursor()
                    cursor.execute("""
                        INSERT INTO weekly_plans (user_id, budget, total_cost, weekly_health_score, grade, plan_data)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            budget = VALUES(budget),
                            total_cost = VALUES(total_cost),
                            weekly_health_score = VALUES(weekly_health_score),
                            grade = VALUES(grade),
                            plan_data = VALUES(plan_data),
                            updated_at = CURRENT_TIMESTAMP
                    """, (
                        user_id,
                        metrics.get('budget'),
                        metrics.get('total_cost', 0),
                        metrics.get('weekly_health_score', 0),
                        metrics.get('grade', ''),
                        plan_json_str
                    ))
                    db.commit()
                    cursor.close()
                    db.close()
                    result['saved'] = True
            except Exception as save_err:
                print(f"Error saving weekly plan: {save_err}")
                result['saved'] = False

        return jsonify(result)
    except Exception as e:
        print(f"Chatbot API error: {e}")
        return jsonify({'success': False, 'message': f"Chatbot error: {str(e)}"}), 500


@app.route('/api/meal-plan', methods=['GET'])
def get_saved_meal_plan():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'User not logged in', 'plan': None})

    try:
        db = get_db_connection()
        if not db:
            return jsonify({'success': False, 'message': 'Database connection error', 'plan': None}), 500
        cursor = db.cursor(dictionary=True)
        cursor.execute("SELECT id, user_id, budget, total_cost, weekly_health_score, grade, plan_data, updated_at FROM weekly_plans WHERE user_id = %s", (user_id,))
        row = cursor.fetchone()
        cursor.close()
        db.close()

        if not row:
            return jsonify({'success': True, 'plan': None})

        plan_data = row['plan_data']
        if isinstance(plan_data, str):
            plan_data = json.loads(plan_data)

        updated_at_str = row['updated_at'].strftime('%b %d, %Y at %I:%M %p') if row.get('updated_at') else None

        return jsonify({
            'success': True,
            'plan': plan_data,
            'updated_at': updated_at_str,
            'weekly_health_score': row.get('weekly_health_score'),
            'total_cost': float(row.get('total_cost', 0))
        })
    except Exception as e:
        print(f"Error fetching saved meal plan: {e}")
        return jsonify({'success': False, 'message': str(e), 'plan': None}), 500


@app.route('/api/meal-plan', methods=['DELETE'])
def clear_saved_meal_plan():
    user_id = session.get('user_id')
    if not user_id:
        return jsonify({'success': False, 'message': 'User not logged in'}), 401

    try:
        db = get_db_connection()
        if not db:
            return jsonify({'success': False, 'message': 'Database connection error'}), 500
        cursor = db.cursor()
        cursor.execute("DELETE FROM weekly_plans WHERE user_id = %s", (user_id,))
        db.commit()
        cursor.close()
        db.close()
        return jsonify({'success': True, 'message': 'Weekly meal plan cleared successfully.'})
    except Exception as e:
        print(f"Error clearing saved meal plan: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    print(f"Starting canteen app on http://127.0.0.1:{port}")
    app.run(debug=True, port=port)


