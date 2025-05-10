from flask import Flask, render_template, request, redirect, session, url_for, flash, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from models import db, User, Review, Installment, ChatMessage, Donation, Category, Listing, ListingImage, CartItem, WishlistItem, Trade, Notification, UserReview
import os
from datetime import datetime, timedelta, timezone
import json
from functools import wraps
import uuid
import math
from sqlalchemy import or_, and_, func

app = Flask(__name__)

# Configuration for the Flask app
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///exchangify.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', os.urandom(24))  # Generate secure random key

# Configure upload folders
UPLOAD_FOLDER = 'static/uploads'
LISTING_IMAGES_FOLDER = 'static/uploads/listings'
PROFILE_IMAGES_FOLDER = 'static/uploads/profiles'

# Create upload directories if they don't exist
for folder in [UPLOAD_FOLDER, LISTING_IMAGES_FOLDER, PROFILE_IMAGES_FOLDER]:
    if not os.path.exists(folder):
        os.makedirs(folder)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['LISTING_IMAGES_FOLDER'] = LISTING_IMAGES_FOLDER
app.config['PROFILE_IMAGES_FOLDER'] = PROFILE_IMAGES_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# Initialize the database with the Flask app
db.init_app(app)

# Function to check if the user is an admin
def requires_admin(f):
    @wraps(f)  # This preserves the original function name and metadata
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for('login'))
        user = User.query.get(session["user_id"])
        if not user or user.role != 'admin':
            flash("Access denied. Admins only.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Function to check if the user is logged in
def requires_login(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in first.", "warning")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def update_user_status(user_id, is_online=True):
    user = User.query.get(user_id)
    if user:
        user.is_online = is_online
        user.last_seen = datetime.utcnow()
        db.session.commit()

def create_notification(user_id, title, message, notification_type, related_id=None):
    notification = Notification(
        user_id=user_id,
        title=title,
        message=message,
        notification_type=notification_type,
        related_id=related_id
    )
    db.session.add(notification)
    db.session.commit()
    return notification

def calculate_distance(lat1, lon1, lat2, lon2):
    # Haversine formula to calculate distance between two points
    R = 6371  # Radius of the Earth in km
    
    # Convert latitude and longitude from degrees to radians
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lat2)
    
    # Differences
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    # Haversine formula
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    distance = R * c
    
    return distance  # Distance in kilometers

@app.route("/reviews")
@requires_admin
def reviews():
    # Get search query if any
    search_query = request.args.get('search', '')
    
    # Fetch reviews based on search query
    if search_query:
        reviews = Review.query.filter(
            (Review.title.contains(search_query)) | 
            (Review.content.contains(search_query)) |
            (Review.tags.contains(search_query))
        ).all()
    else:
        reviews = Review.query.all()
        
    return render_template("reviews_for_admin.html", reviews=reviews, search_query=search_query)

@app.route("/users")
@requires_admin
def users():
    # Get search query if any
    search_query = request.args.get('search', '')
    
    # Fetch users based on search query
    if search_query and search_query.isdigit():
        users = User.query.filter_by(id=int(search_query)).all()
    else:
        users = User.query.all()
        
    return render_template("users_for_admin.html", users=users, search_query=search_query)

@app.route("/delete_user/<int:user_id>", methods=["POST"])
@requires_admin
def delete_user(user_id):
    # Prevent deleting the admin user
    if user_id == session.get("user_id"):
        flash("You cannot delete your own account.", "danger")
        return redirect(url_for('users'))
    
    user = User.query.get_or_404(user_id)
    
    # Delete all reviews by this user
    Review.query.filter_by(user_id=user_id).delete()
    
    # Delete the user
    db.session.delete(user)
    db.session.commit()
    
    flash("User and all their reviews deleted successfully!", "success")
    return redirect(url_for('users'))

# Add a new route to delete reviews
@app.route("/delete_review/<int:review_id>", methods=["POST"])
@requires_admin
def delete_review(review_id):
    review = Review.query.get_or_404(review_id)
    db.session.delete(review)
    db.session.commit()
    flash("Review deleted successfully!", "success")
    return redirect(url_for('reviews'))

# Installment application routes
@app.route("/apply_installment", methods=["GET", "POST"])
@requires_login
def apply_installment():
    if request.method == "POST":
        # Get form data
        amount = request.form.get("amount")
        purpose = request.form.get("purpose")
        duration = request.form.get("duration")
        income = request.form.get("income")
        employment_status = request.form.get("employment_status")
        employer = request.form.get("employer")
        
        # Validate inputs
        if not amount or not purpose or not duration or not income or not employment_status:
            flash("All required fields must be filled!", "danger")
            return redirect(url_for('apply_installment'))
        
        try:
            amount = float(amount)
            duration = int(duration)
            income = float(income)
        except ValueError:
            flash("Invalid amount, duration, or income value", "danger")
            return redirect(url_for('apply_installment'))
        
        # Create new installment application
        new_installment = Installment(
            user_id=session["user_id"],
            amount=amount,
            purpose=purpose,
            duration=duration,
            income=income,
            employment_status=employment_status,
            employer=employer,
            status="pending"
        )
        
        # Add to database
        db.session.add(new_installment)
        db.session.commit()
        
        # Create notification for admin
        admin_users = User.query.filter_by(role='admin').all()
        for admin in admin_users:
            create_notification(
                admin.id,
                "New Installment Application",
                f"A new installment application for ${amount} has been submitted.",
                "installment",
                new_installment.id
            )
        
        flash("Installment application submitted successfully!", "success")
        return redirect(url_for('user_dashboard'))
    
    return render_template("apply_installment.html")

@app.route("/installments")
@requires_admin
def installments():
    # Get search query if any
    search_query = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    
    # Base query
    query = Installment.query.join(User)
    
    # Apply filters
    if search_query:
        if search_query.isdigit():
            query = query.filter(
                (Installment.id == int(search_query)) | 
                (User.id == int(search_query))
            )
        else:
            query = query.filter(
                (User.first_name.contains(search_query)) | 
                (User.last_name.contains(search_query)) |
                (User.email.contains(search_query))
            )
    
    if status_filter:
        query = query.filter(Installment.status == status_filter)
    
    # Order by most recent first
    installments = query.order_by(Installment.created_at.desc()).all()
    
    return render_template(
        "installments_for_admin.html", 
        installments=installments, 
        search_query=search_query,
        status_filter=status_filter
    )

@app.route("/installment/<int:installment_id>")
@requires_admin
def view_installment(installment_id):
    installment = Installment.query.get_or_404(installment_id)
    return render_template("view_installment.html", installment=installment)

@app.route("/update_installment_status/<int:installment_id>", methods=["POST"])
@requires_admin
def update_installment_status(installment_id):
    installment = Installment.query.get_or_404(installment_id)
    
    status = request.form.get("status")
    admin_notes = request.form.get("admin_notes")
    
    if status not in ["approved", "rejected"]:
        flash("Invalid status", "danger")
        return redirect(url_for('installments'))
    
    installment.status = status
    installment.admin_notes = admin_notes
    installment.updated_at = datetime.utcnow()
    
    db.session.commit()
    
    # Create notification for user
    create_notification(
        installment.user_id,
        f"Installment Application {status.capitalize()}",
        f"Your installment application for ${installment.amount} has been {status}.",
        "installment",
        installment.id
    )
    
    flash(f"Installment application {status}", "success")
    return redirect(url_for('installments'))

@app.route("/my_installments")
@requires_login
def my_installments():
    user_id = session["user_id"]
    installments = Installment.query.filter_by(user_id=user_id).order_by(Installment.created_at.desc()).all()
    return render_template("my_installments.html", installments=installments)

# Chat functionality
@app.route("/chat")
@requires_login
def chat():
    users = User.query.filter(User.id != session['user_id']).all()
    
    # Update user's online status
    update_user_status(session['user_id'])
    
    # Mark notifications as read
    unread_chat_notifications = Notification.query.filter_by(
        user_id=session['user_id'],
        notification_type='chat',
        is_read=False
    ).all()
    
    for notification in unread_chat_notifications:
        notification.is_read = True
    
    db.session.commit()
    
    return render_template("chat.html", users=users)

@app.route("/api/users/search", methods=["GET"])
@requires_login
def search_users():
    query = request.args.get("q", "")
    users = User.query.filter(
        (User.id != session['user_id']) & 
        ((User.first_name.like(f"%{query}%")) | 
        (User.last_name.like(f"%{query}%")))
    ).all()
    
    return jsonify([{
        "id": user.id,
        "name": f"{user.first_name} {user.last_name}",
        "isOnline": user.is_online,
        "lastSeen": user.last_seen.isoformat() if user.last_seen else None
    } for user in users])

@app.route("/api/messages/<int:user_id>", methods=["GET"])
@requires_login
def get_messages(user_id):
    current_user_id = session['user_id']
    
    messages = ChatMessage.query.filter(
        ((ChatMessage.sender_id == current_user_id) & (ChatMessage.receiver_id == user_id)) |
        ((ChatMessage.sender_id == user_id) & (ChatMessage.receiver_id == current_user_id))
    ).order_by(ChatMessage.timestamp).all()
    
    # Mark messages as read
    unread_messages = [msg for msg in messages if msg.receiver_id == current_user_id and not msg.is_read]
    for msg in unread_messages:
        msg.is_read = True
    
    db.session.commit()
    
    return jsonify([{
        "id": msg.id,
        "senderId": msg.sender_id,
        "text": msg.message,
        "type": msg.message_type,
        "mediaUrl": msg.media_url if msg.message_type == "image" else None,
        "isRead": msg.is_read,
        "timestamp": msg.timestamp.isoformat()
    } for msg in messages])

@app.route("/api/messages/send", methods=["POST"])
@requires_login
def send_message():
    current_user_id = session['user_id']
    
    data = request.json
    receiver_id = data.get("receiverId")
    message_text = data.get("message")
    message_type = data.get("type", "text")
    media_url = data.get("mediaUrl")
    
    if not receiver_id or (not message_text and message_type == "text"):
        return jsonify({"error": "Missing required fields"}), 400
    
    message = ChatMessage(
        sender_id=current_user_id,
        receiver_id=receiver_id,
        message=message_text,
        message_type=message_type,
        media_url=media_url
    )
    
    db.session.add(message)
    db.session.commit()
    
    # Create notification for receiver
    sender = User.query.get(current_user_id)
    create_notification(
        receiver_id,
        "New Message",
        f"You have a new message from {sender.first_name} {sender.last_name}",
        "chat",
        message.id
    )
    
    return jsonify({
        "id": message.id,
        "senderId": message.sender_id,
        "text": message.message,
        "type": message.message_type,
        "mediaUrl": message.media_url,
        "isRead": message.is_read,
        "timestamp": message.timestamp.isoformat()
    })

@app.route("/api/messages/upload", methods=["POST"])
@requires_login
def upload_message_image():
    if 'image' not in request.files:
        return jsonify({"error": "No file part"}), 400
    
    file = request.files['image']
    
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    if file and allowed_file(file.filename):
        # Generate unique filename
        filename = secure_filename(file.filename)
        unique_filename = f"{uuid.uuid4()}_{filename}"
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], 'chat', unique_filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        file.save(file_path)
        
        # Return the URL to the uploaded file
        file_url = url_for('static', filename=f'uploads/chat/{unique_filename}')
        return jsonify({"url": file_url})
    
    return jsonify({"error": "File type not allowed"}), 400

@app.route("/api/messages/delete/<int:message_id>", methods=["DELETE"])
@requires_login
def delete_message(message_id):
    message = ChatMessage.query.get_or_404(message_id)
    
    # Only allow the sender to delete their own messages
    if message.sender_id != session['user_id']:
        return jsonify({"error": "Unauthorized"}), 403
    
    db.session.delete(message)
    db.session.commit()
    
    return jsonify({"success": True})

# Donation functionality
@app.route("/donations")
@requires_login
def donations():
    # Get donations made by the user
    donations_made = Donation.query.filter_by(donor_id=session['user_id']).all()
    
    # Get donations received by the user
    donations_received = Donation.query.filter_by(recipient_id=session['user_id']).all()
    
    # Get admin donations if the current user is an admin
    current_user = User.query.get(session['user_id'])
    admin_donations = []
    if current_user.role == 'admin':
        admin_donations = Donation.query.filter_by(is_admin_donation=True).all()
    
    return render_template("donations.html", 
                          donations_made=donations_made, 
                          donations_received=donations_received,
                          admin_donations=admin_donations,
                          is_admin=(current_user.role == 'admin'))

@app.route("/donations/new", methods=["GET", "POST"])
@requires_login
def new_donation():
    if request.method == "POST":
        recipient_type = request.form.get("recipient_type")
        recipient_id = None
        is_admin_donation = False
        
        if recipient_type == "user":
            recipient_id = request.form.get("recipient_id")
            if not recipient_id:
                flash("Please select a recipient", "danger")
                return redirect(url_for("new_donation"))
        elif recipient_type == "admin":
            is_admin_donation = True
        
        item_name = request.form.get("item_name")
        description = request.form.get("description")
        condition = request.form.get("condition")
        
        # Handle image upload
        image_filename = None
        if 'item_image' in request.files:
            file = request.files['item_image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Add timestamp to filename to make it unique
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                image_filename = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))
        
        # Create new donation
        donation = Donation(
            donor_id=session['user_id'],
            recipient_id=recipient_id,
            item_name=item_name,
            description=description,
            condition=condition,
            image_filename=image_filename,
            status="pending",
            is_admin_donation=is_admin_donation
        )
        
        db.session.add(donation)
        db.session.commit()
        
        # Create notification for recipient
        if recipient_id:
            create_notification(
                recipient_id,
                "New Donation Offer",
                f"You have received a donation offer for: {item_name}",
                "donation",
                donation.id
            )
        elif is_admin_donation:
            # Notify all admins
            admins = User.query.filter_by(role='admin').all()
            for admin in admins:
                create_notification(
                    admin.id,
                    "New Donation to Organization",
                    f"A new donation has been offered: {item_name}",
                    "donation",
                    donation.id
                )
        
        flash("Donation created successfully!", "success")
        return redirect(url_for("donations"))
    
    # Get all users except current user
    users = User.query.filter(User.id != session['user_id']).all()
    return render_template("new_donation.html", users=users)

@app.route("/donations/<int:donation_id>")
@requires_login
def view_donation(donation_id):
    donation = Donation.query.get_or_404(donation_id)
    current_user = User.query.get(session['user_id'])
    
    # Check if user is either donor, recipient, or admin (for admin donations)
    if (donation.donor_id != session['user_id'] and 
        donation.recipient_id != session['user_id'] and 
        not (current_user.role == 'admin' and donation.is_admin_donation)):
        flash("You don't have permission to view this donation", "danger")
        return redirect(url_for("donations"))
    
    return render_template("view_donation.html", donation=donation, is_admin=(current_user.role == 'admin'))

@app.route("/donations/<int:donation_id>/update_status", methods=["POST"])
@requires_login
def update_donation_status(donation_id):
    donation = Donation.query.get_or_404(donation_id)
    current_user = User.query.get(session['user_id'])
    
    # Check if user is recipient or admin (for admin donations)
    if (donation.recipient_id != session['user_id'] and 
        not (current_user.role == 'admin' and donation.is_admin_donation)):
        flash("You don't have permission to update this donation", "danger")
        return redirect(url_for("donations"))
    
    new_status = request.form.get("status")
    if new_status in ["accepted", "declined", "completed"]:
        donation.status = new_status
        db.session.commit()
        
        # Create notification for donor
        status_message = "accepted" if new_status == "accepted" else "declined" if new_status == "declined" else "marked as received"
        create_notification(
            donation.donor_id,
            f"Donation {status_message.capitalize()}",
            f"Your donation of {donation.item_name} has been {status_message}.",
            "donation",
            donation.id
        )
        
        flash(f"Donation {new_status} successfully!", "success")
    
    return redirect(url_for("view_donation", donation_id=donation_id))

# Listing Management Routes
@app.route("/listings")
def listings():
    # Get filter parameters
    category_id = request.args.get('category', type=int)
    listing_type = request.args.get('type')
    condition = request.args.get('condition')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    search_query = request.args.get('q', '')
    radius = request.args.get('radius', type=int)  # None if not provided

    # Base query
    query = Listing.query.filter_by(is_active=True)

    # Apply filters
    if category_id:
        query = query.filter_by(category_id=category_id)

    if listing_type:
        query = query.filter_by(listing_type=listing_type)

    if condition:
        query = query.filter_by(condition=condition)

    if min_price is not None:
        query = query.filter(Listing.price >= min_price)

    if max_price is not None:
        query = query.filter(Listing.price <= max_price)

    # Case-insensitive search on title or description
    if search_query:
        search_term = search_query.lower()
        query = query.filter(
            or_(
                func.lower(Listing.title).contains(search_term),
                func.lower(Listing.description).contains(search_term)
            )
        )

    # Get all listings that match the filters
    all_listings = query.all()

    # Apply distance filtering only if radius is explicitly provided and greater than 0
    filtered_listings = all_listings
    if radius is not None and radius > 0 and 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user and user.latitude and user.longitude:
            filtered_listings = [
                listing for listing in all_listings
                if listing.latitude and listing.longitude and calculate_distance(
                    user.latitude, user.longitude,
                    listing.latitude, listing.longitude
                ) <= radius
            ]
            # Add distance attribute to filtered listings
            for listing in filtered_listings:
                distance = calculate_distance(
                    user.latitude, user.longitude,
                    listing.latitude, listing.longitude
                )
                listing.distance = round(distance, 1)
        # If user has no location, filtered_listings remains all_listings
    # If radius is None (not provided) or 0, no distance filtering is applied

    # Get all categories for the filter sidebar
    categories = Category.query.all()

    # Get counts for the navbar
    cart_count = 0
    wishlist_count = 0

    if "user_id" in session:
        cart_count = CartItem.query.filter_by(user_id=session["user_id"]).count()
        wishlist_count = WishlistItem.query.filter_by(user_id=session["user_id"]).count()

    return render_template(
        "listings.html",
        listings=filtered_listings,
        categories=categories,
        selected_category=category_id,
        selected_type=listing_type,
        selected_condition=condition,
        min_price=min_price,
        max_price=max_price,
        search_query=search_query,
        radius=radius,
        cart_count=cart_count,
        wishlist_count=wishlist_count
    )

@app.route("/listings/new", methods=["GET", "POST"])
@requires_login
def new_listing():
    if request.method == "POST":
        # Get form data
        title = request.form.get("title")
        description = request.form.get("description")
        condition = request.form.get("condition")
        category_id = request.form.get("category_id")
        listing_type = request.form.get("listing_type")
        price = request.form.get("price") if listing_type == "sale" else None
        exchange_preferences = request.form.get("exchange_preferences") if listing_type == "exchange" else None
        loan_duration = request.form.get("loan_duration") if listing_type == "loan" else None
        location = request.form.get("location")
        latitude = request.form.get("latitude")
        longitude = request.form.get("longitude")
        
        # Validate required fields
        if not title or not description or not condition or not category_id or not listing_type:
            flash("Please fill in all required fields", "danger")
            return redirect(url_for("new_listing"))
        
        # Create new listing
        listing = Listing(
            title=title,
            description=description,
            condition=condition,
            category_id=category_id,
            listing_type=listing_type,
            price=price,
            exchange_preferences=exchange_preferences,
            loan_duration=loan_duration,
            location=location,
            latitude=latitude,
            longitude=longitude,
            user_id=session['user_id']
        )
        
        db.session.add(listing)
        db.session.commit()
        
        # Handle image uploads
        if 'images' in request.files:
            images = request.files.getlist('images')
            for i, image in enumerate(images):
                if image and image.filename != '' and allowed_file(image.filename):
                    filename = secure_filename(image.filename)
                    # Add unique identifier to filename
                    unique_filename = f"{uuid.uuid4()}_{filename}"
                    file_path = os.path.join(app.config['LISTING_IMAGES_FOLDER'], unique_filename)
                    image.save(file_path)
                    
                    # Create listing image record
                    listing_image = ListingImage(
                        filename=unique_filename,
                        is_primary=(i == 0),  # First image is primary
                        listing_id=listing.id
                    )
                    db.session.add(listing_image)
        
        db.session.commit()
        
        flash("Listing created successfully!", "success")
        return redirect(url_for("view_listing", listing_id=listing.id))
    
    # Get all categories for the form
    categories = Category.query.all()
    
    return render_template("new_listing.html", categories=categories)

@app.route("/listings/<int:listing_id>")
def view_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    # Increment view count
    listing.views += 1
    db.session.commit()
    
    # Check if the listing is in the user's wishlist
    in_wishlist = False
    if 'user_id' in session:
        wishlist_item = WishlistItem.query.filter_by(
            user_id=session['user_id'],
            listing_id=listing.id
        ).first()
        in_wishlist = wishlist_item is not None
    
    # Get similar listings (same category)
    similar_listings = Listing.query.filter(
        Listing.category_id == listing.category_id,
        Listing.id != listing.id,
        Listing.is_active == True
    ).limit(4).all()
    
    return render_template(
        "view_listing.html",
        listing=listing,
        in_wishlist=in_wishlist,
        similar_listings=similar_listings
    )

@app.route("/listings/<int:listing_id>/edit", methods=["GET", "POST"])
@requires_login
def edit_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    # Check if user is the owner
    if listing.user_id != session['user_id']:
        flash("You don't have permission to edit this listing", "danger")
        return redirect(url_for("view_listing", listing_id=listing.id))
    
    if request.method == "POST":
        # Update listing data
        listing.title = request.form.get("title")
        listing.description = request.form.get("description")
        listing.condition = request.form.get("condition")
        listing.category_id = request.form.get("category_id")
        listing.listing_type = request.form.get("listing_type")
        
        if listing.listing_type == "sale":
            listing.price = request.form.get("price")
            listing.exchange_preferences = None
            listing.loan_duration = None
        elif listing.listing_type == "exchange":
            listing.price = None
            listing.exchange_preferences = request.form.get("exchange_preferences")
            listing.loan_duration = None
        elif listing.listing_type == "loan":
            listing.price = None
            listing.exchange_preferences = None
            listing.loan_duration = request.form.get("loan_duration")
        else:  # donation
            listing.price = None
            listing.exchange_preferences = None
            listing.loan_duration = None
        
        listing.location = request.form.get("location")
        listing.latitude = request.form.get("latitude")
        listing.longitude = request.form.get("longitude")
        
        # Handle new image uploads
        if 'new_images' in request.files:
            new_images = request.files.getlist('new_images')
            for image in new_images:
                if image and image.filename != '' and allowed_file(image.filename):
                    filename = secure_filename(image.filename)
                    unique_filename = f"{uuid.uuid4()}_{filename}"
                    file_path = os.path.join(app.config['LISTING_IMAGES_FOLDER'], unique_filename)
                    image.save(file_path)
                    
                    # Create listing image record
                    listing_image = ListingImage(
                        filename=unique_filename,
                        is_primary=False,  # New images are not primary by default
                        listing_id=listing.id
                    )
                    db.session.add(listing_image)
        
        # Handle deleted images
        deleted_images = request.form.getlist("delete_image")
        for image_id in deleted_images:
            image = ListingImage.query.get(image_id)
            if image and image.listing_id == listing.id:
                # Delete the file
                try:
                    os.remove(os.path.join(app.config['LISTING_IMAGES_FOLDER'], image.filename))
                except:
                    pass  # File might not exist
                
                # Delete the record
                db.session.delete(image)
        
        # Handle primary image
        primary_image_id = request.form.get("primary_image")
        if primary_image_id:
            # Reset all images to non-primary
            for image in listing.images:
                image.is_primary = (str(image.id) == primary_image_id)
        
        db.session.commit()
        
        flash("Listing updated successfully!", "success")
        return redirect(url_for("view_listing", listing_id=listing.id))
    
    # Get all categories for the form
    categories = Category.query.all()
    
    return render_template("edit_listing.html", listing=listing, categories=categories)

@app.route("/listings/<int:listing_id>/delete", methods=["POST"])
@requires_login
def delete_listing(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    # Check if user is the owner
    if listing.user_id != session['user_id'] and not User.query.get(session['user_id']).role == 'admin':
        flash("You don't have permission to delete this listing", "danger")
        return redirect(url_for("view_listing", listing_id=listing.id))
    
    # Delete all images
    for image in listing.images:
        try:
            os.remove(os.path.join(app.config['LISTING_IMAGES_FOLDER'], image.filename))
        except:
            pass  # File might not exist
    
    # Delete the listing
    db.session.delete(listing)
    db.session.commit()
    
    flash("Listing deleted successfully!", "success")
    return redirect(url_for("my_listings"))

@app.route("/my_listings")
@requires_login
def my_listings():
    listings = Listing.query.filter_by(user_id=session['user_id']).order_by(Listing.created_at.desc()).all()
    return render_template("my_listings.html", listings=listings)

# Cart and Wishlist Routes
@app.route("/cart")
@requires_login
def view_cart():
    cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()
    
    # Calculate total price (quantity is always 1)
    total_price = sum(item.listing.price for item in cart_items if item.listing.price)
    
    return render_template("cart.html", cart_items=cart_items, total_price=total_price)

@app.route("/api/cart/add", methods=["POST"])
@requires_login
def add_to_cart():
    data = request.json
    listing_id = data.get("listing_id")
    
    if not listing_id:
        return jsonify({"error": "Listing ID is required"}), 400
    
    # Check if listing exists and is active
    listing = Listing.query.get_or_404(listing_id)
    if not listing.is_active:
        return jsonify({"error": "This listing is no longer available"}), 400
    
    # Check if listing is for sale
    if listing.listing_type != "sale":
        return jsonify({"error": "Only items for sale can be added to cart"}), 400
    
    # Check if item is already in cart
    cart_item = CartItem.query.filter_by(
        user_id=session['user_id'],
        listing_id=listing_id
    ).first()
    
    if cart_item:
        return jsonify({"error": "This item is already in your cart"}), 400
    
    # Add item to cart with quantity 1
    cart_item = CartItem(
        user_id=session['user_id'],
        listing_id=listing_id,
        quantity=1  # Always set to 1
    )
    db.session.add(cart_item)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Item added to cart",
        "cart_count": CartItem.query.filter_by(user_id=session['user_id']).count()
    })



@app.route("/api/cart/remove/<int:cart_item_id>", methods=["DELETE"])
@requires_login
def remove_from_cart(cart_item_id):
    cart_item = CartItem.query.get_or_404(cart_item_id)
    
    # Check if user owns this cart item
    if cart_item.user_id != session['user_id']:
        return jsonify({"error": "Unauthorized"}), 403
    
    db.session.delete(cart_item)
    db.session.commit()
    
    return jsonify({
        "success": True,
        "message": "Item removed from cart",
        "cart_count": CartItem.query.filter_by(user_id=session['user_id']).count()
    })

@app.route("/wishlist")
@requires_login
def view_wishlist():
    wishlist_items = WishlistItem.query.filter_by(user_id=session['user_id']).all()
    return render_template("wishlist.html", wishlist_items=wishlist_items)

@app.route("/api/wishlist/toggle", methods=["POST"])
@requires_login
def toggle_wishlist():
    data = request.json
    listing_id = data.get("listing_id")
    
    if not listing_id:
        return jsonify({"error": "Listing ID is required"}), 400
    
    # Check if listing exists
    listing = Listing.query.get_or_404(listing_id)
    
    # Check if item is already in wishlist
    wishlist_item = WishlistItem.query.filter_by(
        user_id=session['user_id'],
        listing_id=listing_id
    ).first()
    
    if wishlist_item:
        # Remove from wishlist
        db.session.delete(wishlist_item)
        db.session.commit()
        return jsonify({
            "success": True,
            "in_wishlist": False,
            "message": "Item removed from wishlist"
        })
    else:
        # Add to wishlist
        wishlist_item = WishlistItem(
            user_id=session['user_id'],
            listing_id=listing_id
        )
        db.session.add(wishlist_item)
        db.session.commit()
        return jsonify({
            "success": True,
            "in_wishlist": True,
            "message": "Item added to wishlist"
        })

# Trade Routes
@app.route("/trades")
@requires_login
def my_trades():
    # Get trades where user is either initiator or receiver
    user_id = session['user_id']
    
    initiated_trades = Trade.query.filter_by(initiator_id=user_id).all()
    received_trades = Trade.query.filter_by(receiver_id=user_id).all()
    
    return render_template(
        "my_trades.html",
        initiated_trades=initiated_trades,
        received_trades=received_trades
    )

@app.route("/trades/new/<int:listing_id>", methods=["GET", "POST"])
@requires_login
def new_trade(listing_id):
    listing = Listing.query.get_or_404(listing_id)
    
    # Check if listing is active
    if not listing.is_active:
        flash("This listing is no longer available", "danger")
        return redirect(url_for("listings"))
    
    # Check if user is not the owner
    if listing.user_id == session['user_id']:
        flash("You cannot trade with yourself", "danger")
        return redirect(url_for("view_listing", listing_id=listing.id))
    
    if request.method == "POST":
        trade_type = request.form.get("trade_type")
        message = request.form.get("message")
        offered_listing_id = request.form.get("offered_listing_id") if trade_type == "exchange" else None
        
        # Validate trade type
        if trade_type not in ["exchange", "loan", "donation"]:
            flash("Invalid trade type", "danger")
            return redirect(url_for("new_trade", listing_id=listing.id))
        
        # For exchanges, validate offered listing
        if trade_type == "exchange" and not offered_listing_id:
            flash("Please select an item to offer for exchange", "danger")
            return redirect(url_for("new_trade", listing_id=listing.id))
        
        # Create new trade
        trade = Trade(
            initiator_id=session['user_id'],
            receiver_id=listing.user_id,
            listing_id=listing.id,
            offered_listing_id=offered_listing_id,
            trade_type=trade_type,
            message=message,
            status="pending"
        )
        
        # For loans, set return date
        if trade_type == "loan" and listing.loan_duration:
            trade.loan_return_date = datetime.utcnow() + timedelta(days=int(listing.loan_duration))
        
        db.session.add(trade)
        db.session.commit()
        
        # Create notification for receiver
        create_notification(
            listing.user_id,
            "New Trade Request",
            f"You have received a new {trade_type} request for your listing: {listing.title}",
            "trade",
            trade.id
        )
        
        flash("Trade request sent successfully!", "success")
        return redirect(url_for("my_trades"))
    
    # Get user's listings for exchange
    user_listings = Listing.query.filter_by(
        user_id=session['user_id'],
        is_active=True
    ).all()
    
    return render_template(
        "new_trade.html",
        listing=listing,
        user_listings=user_listings
    )

@app.route("/trades/<int:trade_id>")
@requires_login
def view_trade(trade_id):
    trade = Trade.query.get_or_404(trade_id)
    
    # Check if user is involved in this trade
    if trade.initiator_id != session['user_id'] and trade.receiver_id != session['user_id']:
        flash("You don't have permission to view this trade", "danger")
        return redirect(url_for("my_trades"))
    
    # Get current UTC time
    now = datetime.utcnow()
    
    return render_template("view_trade.html", trade=trade, now=now)

@app.route("/trades/<int:trade_id>/update", methods=["POST"])
@requires_login
def update_trade_status(trade_id):
    trade = Trade.query.get_or_404(trade_id)
    if trade.receiver_id != session['user_id']:
        flash("You don't have permission to update this trade", "danger")
        return redirect(url_for("view_trade", trade_id=trade.id))
    
    new_status = request.form.get("status")
    if new_status not in ["accepted", "rejected", "completed"]:
        flash("Invalid status", "danger")
        return redirect(url_for("view_trade", trade_id=trade.id))
    
    trade.status = new_status
    
    if new_status == "completed":
        # Mark the listing(s) inactive for all trade types when completed
        listing = Listing.query.get(trade.listing_id)
        listing.is_active = False
        if trade.trade_type == "exchange" and trade.offered_listing_id:
            offered_listing = Listing.query.get(trade.offered_listing_id)
            offered_listing.is_active = False
        
        # Notify both parties
        create_notification(
            trade.initiator_id,
            "Trade Completed",
            f"Your {trade.trade_type} for {trade.listing.title} has been completed.",
            "trade",
            trade.id
        )
        create_notification(
            trade.receiver_id,
            "Trade Completed",
            f"The {trade.trade_type} for {trade.listing.title} has been completed.",
            "trade",
            trade.id
        )
    else:
        # Notify initiator for 'accepted' or 'rejected'
        status_message = "accepted" if new_status == "accepted" else "rejected"
        create_notification(
            trade.initiator_id,
            f"Trade Request {status_message.capitalize()}",
            f"Your {trade.trade_type} request for {trade.listing.title} has been {status_message}.",
            "trade",
            trade.id
        )
    
    db.session.commit()
    flash(f"Trade {new_status} successfully!", "success")
    return redirect(url_for("view_trade", trade_id=trade.id))

# User Review Routes
@app.route("/reviews/user/<int:user_id>")
def user_reviews(user_id):
    user = User.query.get_or_404(user_id)
    reviews = UserReview.query.filter_by(reviewed_id=user_id).all()
    
    # Calculate average rating
    if reviews:
        avg_rating = sum(review.rating for review in reviews) / len(reviews)
    else:
        avg_rating = 0
    
    return render_template(
        "user_reviews.html",
        user=user,
        reviews=reviews,
        avg_rating=avg_rating
    )

@app.route("/reviews/new/<int:trade_id>", methods=["GET", "POST"])
@requires_login
def new_user_review(trade_id):
    trade = Trade.query.get_or_404(trade_id)
    
    # Check if user is involved in this trade
    if trade.initiator_id != session['user_id'] and trade.receiver_id != session['user_id']:
        flash("You don't have permission to review this trade", "danger")
        return redirect(url_for("my_trades"))
    
    # Check if trade is completed
    if trade.status != "completed":
        flash("You can only review completed trades", "danger")
        return redirect(url_for("view_trade", trade_id=trade.id))
    
    # Determine who to review
    if trade.initiator_id == session['user_id']:
        reviewed_id = trade.receiver_id
    else:
        reviewed_id = trade.initiator_id
    
    # Check if user has already reviewed this trade
    existing_review = UserReview.query.filter_by(
        reviewer_id=session['user_id'],
        trade_id=trade.id
    ).first()
    
    if existing_review:
        flash("You have already reviewed this trade", "danger")
        return redirect(url_for("view_trade", trade_id=trade.id))
    
    if request.method == "POST":
        rating = request.form.get("rating")
        comment = request.form.get("comment")
        
        # Validate rating
        try:
            rating = int(rating)
            if rating < 1 or rating > 5:
                raise ValueError
        except:
            flash("Rating must be between 1 and 5", "danger")
            return redirect(url_for("new_user_review", trade_id=trade.id))
        
        # Create new review
        review = UserReview(
            reviewer_id=session['user_id'],
            reviewed_id=reviewed_id,
            trade_id=trade.id,
            rating=rating,
            comment=comment
        )
        
        db.session.add(review)
        db.session.commit()
        
        # Create notification for reviewed user
        create_notification(
            reviewed_id,
            "New Review",
            f"You have received a new review for a trade.",
            "review",
            review.id
        )
        
        flash("Review submitted successfully!", "success")
        return redirect(url_for("view_trade", trade_id=trade.id))
    
    # Get user to review
    reviewed_user = User.query.get(reviewed_id)
    
    return render_template(
        "new_user_review.html",
        trade=trade,
        reviewed_user=reviewed_user
    )

# Notification Routes
@app.route("/notifications")
@requires_login
def notifications():
    user_notifications = Notification.query.filter_by(
        user_id=session['user_id']
    ).order_by(Notification.created_at.desc()).all()
    
    
    return render_template("notifications.html", notifications=user_notifications)

@app.route("/api/notifications/read/<int:notification_id>", methods=["POST"])
@requires_login
def mark_notification_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    if notification.user_id != session['user_id']:
        return jsonify({"error": "Unauthorized"}), 403
    notification.is_read = True
    db.session.commit()
    return jsonify({"success": True})

@app.route("/api/notifications/count")
@requires_login
def notification_count():
    count = Notification.query.filter_by(
        user_id=session['user_id'],
        is_read=False
    ).count()
    
    return jsonify({"count": count})

@app.route("/api/notifications/recent")
@requires_login
def recent_notifications():
    notifications = Notification.query.filter_by(
        user_id=session['user_id']
    ).order_by(Notification.created_at.desc()).limit(5).all()
    
    return jsonify([{
        "id": notification.id,
        "title": notification.title,
        "message": notification.message,
        "type": notification.notification_type,
        "isRead": notification.is_read,
        "createdAt": notification.created_at.isoformat()
    } for notification in notifications])

# Ensure the admin user exists (run this once)
with app.app_context():
    db.create_all()  # Create database tables (if they don't exist)
    
    # Create admin user if it doesn't exist
    admin = User.query.filter_by(email="admin@example.com").first()
    if not admin:
        admin = User(
            email="admin@example.com",
            password=generate_password_hash("adminpassword123"),
            role="admin",
            first_name="Admin",
            last_name="User"
        )
        db.session.add(admin)
        
    # Create default categories if they don't exist
    categories = [
        {"name": "Electronics", "description": "Electronic devices and gadgets"},
        {"name": "Clothing", "description": "Apparel and fashion items"},
        {"name": "Home & Garden", "description": "Items for home and garden"},
        {"name": "Books", "description": "Books, textbooks, and literature"},
        {"name": "Sports & Outdoors", "description": "Sports equipment and outdoor gear"},
        {"name": "Toys & Games", "description": "Toys, games, and entertainment items"},
        {"name": "Vehicles", "description": "Cars, bikes, and other vehicles"},
        {"name": "Collectibles", "description": "Collectible items and memorabilia"}
    ]
    
    for category_data in categories:
        if not Category.query.filter_by(name=category_data["name"]).first():
            category = Category(
                name=category_data["name"],
                description=category_data["description"]
            )
            db.session.add(category)
    
    db.session.commit()

# Routes
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email").strip()
        password = request.form.get("password")
        role = request.form.get("role")
        
        if not email or not password or not role:
            flash("All fields are required", "danger")
            return redirect(url_for('login'))
        
        # Check if user exists with the given email
        user = User.query.filter_by(email=email).first()
        
        if not user:
            flash("Invalid email or password", "danger")
            return redirect(url_for('login'))
        
        # Verify password
        if not check_password_hash(user.password, password):
            flash("Invalid email or password", "danger")
            return redirect(url_for('login'))
        
        # Check if role matches
        if user.role != role:
            flash(f"This account is not registered as a {role}", "danger")
            return redirect(url_for('login'))
        
        # Set user session
        session["user_id"] = user.id
        session["user_name"] = f"{user.first_name} {user.last_name}"
        
        # Update user's online status
        update_user_status(user.id, True)
        
        # Redirect based on role
        if role == "admin":
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('user_dashboard'))
            
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        # Get form data
        email = request.form.get("email").strip()
        password = request.form.get("password")
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        mobile = request.form.get("mobile")
        gender = request.form.get("gender")
        address = request.form.get("address")
        city = request.form.get("city")
        state = request.form.get("state")
        zip_code = request.form.get("zip_code")
        country = request.form.get("country", "United States")
        latitude = request.form.get("latitude")
        longitude = request.form.get("longitude")
        
        # Check if the email already exists
        if User.query.filter_by(email=email).first():
            flash("Email already in use. Please try another one.", "danger")
            return redirect(url_for('signup'))
        
        # Handle profile image upload
        profile_image = None
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and file.filename != '' and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                # Add timestamp to filename to make it unique
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                profile_image = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['PROFILE_IMAGES_FOLDER'], profile_image))
        
        # Create new user
        hashed_password = generate_password_hash(password)
        user = User(
            email=email, 
            password=hashed_password, 
            role="user",
            first_name=first_name,
            last_name=last_name,
            mobile=mobile,
            gender=gender,
            address=address,
            city=city,
            state=state,
            zip_code=zip_code,
            country=country,
            latitude=latitude,
            longitude=longitude,
            profile_image=profile_image
        )
        
        # Save to database
        db.session.add(user)
        db.session.commit()

        # Log the user in after sign-up (automatically set session)
        session["user_id"] = user.id  # Store user ID in the session
        session["user_name"] = f"{user.first_name} {user.last_name}"
        
        # Update user's online status
        update_user_status(user.id, True)

        flash("Sign up successful! Welcome!", "success")
        return redirect(url_for('user_dashboard'))  # Redirect to the user dashboard after sign-up
    
    # Add this return statement for GET requests
    return render_template("signup.html")

@app.route("/admin_dashboard")
@requires_admin
def admin_dashboard():
    # Get user count for the dashboard
    user_count = User.query.filter_by(role='user').count()
    # Get recent reviews for the dashboard
    reviews = Review.query.order_by(Review.date.desc()).limit(5).all()
    # Get pending installment applications
    pending_installments = Installment.query.filter_by(status="pending").count()
    # Get pending donation applications
    pending_donations = Donation.query.filter_by(status="pending").count()
    # Get pending trade requests
    pending_trades = Trade.query.filter_by(status="pending").count()
    # Get total listings
    total_listings = Listing.query.count()
    
    # Get purchase trades count
    purchase_trades_count = Trade.query.filter_by(trade_type="purchase").count()
    
    # Get recent purchase trades
    recent_purchase_trades = Trade.query.filter_by(trade_type="purchase").order_by(Trade.created_at.desc()).limit(5).all()
    
    return render_template(
        "admin_dashboard.html", 
        user_count=user_count, 
        reviews=reviews,
        pending_installments=pending_installments,
        pending_donations=pending_donations,
        pending_trades=pending_trades,
        total_listings=total_listings,
        purchase_trades_count=purchase_trades_count,
        recent_purchase_trades=recent_purchase_trades
    )

@app.route("/admin/trades")
@requires_admin
def admin_trades():
    # Get filter parameters
    trade_type = request.args.get('type')
    status = request.args.get('status')
    search_query = request.args.get('q', '')
    
    # Base query
    query = Trade.query
    
    # Apply filters
    if trade_type:
        query = query.filter_by(trade_type=trade_type)
    
    if status:
        query = query.filter_by(status=status)
    
    if search_query:
        query = query.join(User, User.id == Trade.initiator_id).filter(
            (User.first_name.contains(search_query)) |
            (User.last_name.contains(search_query)) |
            (User.email.contains(search_query))
        )
    
    # Order by most recent first
    trades = query.order_by(Trade.created_at.desc()).all()
    
    return render_template(
        "admin_trades.html", 
        trades=trades, 
        trade_type=trade_type,
        status=status,
        search_query=search_query
    )

@app.route("/user_dashboard")
@requires_login
def user_dashboard():
    user = User.query.get(session["user_id"])  # Fetch user from the database using the session ID
    
    # Get user's installment applications
    installments = Installment.query.filter_by(user_id=user.id).order_by(Installment.created_at.desc()).limit(3).all()
    
    # Get user's donations
    donations_made = Donation.query.filter_by(donor_id=user.id).order_by(Donation.created_at.desc()).limit(3).all()
    donations_received = Donation.query.filter_by(recipient_id=user.id).order_by(Donation.created_at.desc()).limit(3).all()
    
    # Get user's chat messages
    recent_chats = db.session.query(User, db.func.max(ChatMessage.timestamp).label('last_message_time'))\
        .join(ChatMessage, ((ChatMessage.sender_id == User.id) & (ChatMessage.receiver_id == user.id)) | 
                          ((ChatMessage.receiver_id == User.id) & (ChatMessage.sender_id == user.id)))\
        .filter(User.id != user.id)\
        .group_by(User.id)\
        .order_by(db.desc('last_message_time'))\
        .limit(3)\
        .all()
    
    # Get user's recent listings
    recent_listings = Listing.query.filter_by(user_id=user.id).order_by(Listing.created_at.desc()).limit(3).all()
    
    # Get user's recent trades
    recent_trades = Trade.query.filter(
        ((Trade.initiator_id == user.id) | (Trade.receiver_id == user.id))
    ).order_by(Trade.created_at.desc()).limit(3).all()
    
    # Get unread notification count
    unread_notifications = Notification.query.filter_by(
        user_id=user.id,
        is_read=False
    ).count()
    
    # Get wishlist count
    wishlist_count = WishlistItem.query.filter_by(user_id=user.id).count()
    
    # Get cart count
    cart_count = CartItem.query.filter_by(user_id=user.id).count()
    
    return render_template(
        "user_dashboard.html", 
        user=user, 
        installments=installments,
        donations_made=donations_made,
        donations_received=donations_received,
        recent_chats=recent_chats,
        recent_listings=recent_listings,
        recent_trades=recent_trades,
        unread_notifications=unread_notifications,
        wishlist_count=wishlist_count,
        cart_count=cart_count
    )

@app.route("/profile/<int:user_id>")
def user_profile(user_id):
    user = User.query.get_or_404(user_id)
    
    # Get user's reviews
    reviews = UserReview.query.filter_by(reviewed_id=user_id).all()
    
    # Calculate average rating
    if reviews:
        avg_rating = sum(review.rating for review in reviews) / len(reviews)
    else:
        avg_rating = 0
    
    # Get user's active listings
    active_listings = Listing.query.filter_by(
        user_id=user_id,
        is_active=True
    ).order_by(Listing.created_at.desc()).limit(4).all()
    
    return render_template(
        "user_profile.html",
        user=user,
        reviews=reviews,
        avg_rating=avg_rating,
        active_listings=active_listings
    )

@app.route("/edit_profile", methods=["GET", "POST"])
@requires_login
def edit_profile():
    user = User.query.get_or_404(session['user_id'])

    if request.method == "POST":
        # Update basic info
        user.first_name = request.form.get("first_name")
        user.last_name = request.form.get("last_name")
        user.email = request.form.get("email")
        user.mobile = request.form.get("mobile")
        user.gender = request.form.get("gender")
        user.address = request.form.get("address")
        user.city = request.form.get("city")
        user.state = request.form.get("state")
        user.zip_code = request.form.get("zip_code")
        user.country = request.form.get("country")
        user.latitude = request.form.get("latitude")
        user.longitude = request.form.get("longitude")
        
        # Update password if provided
        new_password = request.form.get("new_password")
        if new_password:
            current_password = request.form.get("current_password")
            if not check_password_hash(user.password, current_password):
                flash("Current password is incorrect", "danger")
                return redirect(url_for('edit_profile'))
            
            user.password = generate_password_hash(new_password)
        
        # Handle profile image upload
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and file.filename != '' and allowed_file(file.filename):
                # Delete old profile image if exists
                if user.profile_image:
                    try:
                        os.remove(os.path.join(app.config['PROFILE_IMAGES_FOLDER'], user.profile_image))
                    except:
                        pass  # File might not exist
                
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                profile_image = f"{timestamp}_{filename}"
                file.save(os.path.join(app.config['PROFILE_IMAGES_FOLDER'], profile_image))
                user.profile_image = profile_image

        db.session.commit()  # Save the updated profile to the database
        flash("Profile updated successfully", "success")
        return redirect(url_for('user_profile', user_id=user.id))

    return render_template("edit_profile.html", user=user)

@app.route("/add_review", methods=["GET", "POST"])
def add_review():
    if "user_id" not in session:
        flash("You need to log in to submit a review.", "warning")
        return redirect(url_for('login'))

    if request.method == "POST":
        title = request.form.get("title").strip()
        content = request.form.get("content").strip()
        tags = request.form.get("tags")
        date = request.form.get("date")

        # Validate inputs
        if not title or not content or not tags or not date:
            flash("All fields are required!", "danger")
            return redirect(url_for('add_review'))

        try:
            date_obj = datetime.strptime(date, "%Y-%m-%d")  # Convert string to datetime object
        except ValueError:
            flash("Invalid date format", "danger")
            return redirect(url_for('add_review'))

        # Create new review
        new_review = Review(
            title=title,
            content=content,
            tags=tags,
            date=date_obj,
            user_id=session["user_id"]
        )

        # Add the review to the database
        db.session.add(new_review)
        db.session.commit()

        flash("Review added successfully!", "success")
        return redirect(url_for('user_dashboard'))  # Redirect back to the dashboard after success

    return render_template("add_review_for_user.html")  # Ensure you return the template if it's a GET request

@app.route("/logout")
def logout():
    # Update user's online status if logged in
    if "user_id" in session:
        update_user_status(session["user_id"], False)
    
    session.clear()  # Clear all session data
    flash("You have successfully logged out.", "info")  # Notify user they logged out
    return redirect(url_for('login'))  # Redirect to login page after logging out
@app.route("/home")
def home():
    # Get featured listings
    featured_listings = Listing.query.filter_by(is_active=True).order_by(func.random()).limit(8).all()
    
    # Get categories
    categories = Category.query.all()
    
    # Get recent trades
    recent_trades = Trade.query.filter_by(status="completed").order_by(Trade.updated_at.desc()).limit(3).all()
    
    # Get counts for the navbar
    cart_count = 0
    wishlist_count = 0
    notification_count = 0
    
    if "user_id" in session:
        cart_count = CartItem.query.filter_by(user_id=session["user_id"]).count()
        wishlist_count = WishlistItem.query.filter_by(user_id=session["user_id"]).count()
        notification_count = Notification.query.filter_by(user_id=session["user_id"], is_read=False).count()
    
    return render_template(
        "home.html", 
        featured_listings=featured_listings,
        categories=categories,
        recent_trades=recent_trades,
        cart_count=cart_count,
        wishlist_count=wishlist_count,
        notification_count=notification_count
    )

# Add this route to your app.py file to handle checkout
@app.route("/checkout")
@requires_login
def checkout():
    # Get cart items
    cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()
    
    # If cart is empty, redirect to cart page
    if not cart_items:
        flash("Your cart is empty", "warning")
        return redirect(url_for('view_cart'))
    
    # Get user info for pre-filling the form
    user = User.query.get(session['user_id'])
    
    # Calculate total price (quantity is always 1)
    total_price = sum(item.listing.price for item in cart_items if item.listing.price)
    
    return render_template(
        "checkout.html", 
        cart_items=cart_items, 
        total_price=total_price,
        user=user
    )

# Add this route to process orders
@app.route("/api/place_order", methods=["POST"])
@requires_login
def place_order():
    cart_items = CartItem.query.filter_by(user_id=session['user_id']).all()
    if not cart_items:
        return jsonify({"error": "Your cart is empty"}), 400
    
    for item in cart_items:
        trade = Trade(
            initiator_id=session['user_id'],
            receiver_id=item.listing.user_id,
            listing_id=item.listing.id,
            trade_type="purchase",
            message="Order placed through checkout",
            status="completed"  # Set to 'completed' directly
        )
        db.session.add(trade)
        
        # Mark the listing as inactive since the trade is completed
        listing = item.listing
        listing.is_active = False
        
        # Notify the seller
        create_notification(
            item.listing.user_id,
            "Purchase Completed",
            f"A purchase has been completed for your listing: {item.listing.title}",
            "trade",
            trade.id
        )
        
        # Notify the buyer
        create_notification(
            session['user_id'],
            "Order Placed",
            f"You have successfully placed an order for {item.listing.title}.",
            "trade",
            trade.id
        )
    
    # Clear the cart
    for item in cart_items:
        db.session.delete(item)
    
    db.session.commit()
    
    return jsonify({"success": True, "message": "Order placed successfully"})

@app.route("/api/listings", methods=["GET"])
def get_listings():
    category_id = request.args.get('category', type=int)
    listing_type = request.args.get('type')
    condition = request.args.get('condition')
    min_price = request.args.get('min_price', type=float)
    max_price = request.args.get('max_price', type=float)
    search_query = request.args.get('q', '')
    
    query = Listing.query.filter_by(is_active=True)
    
    if category_id:
        query = query.filter_by(category_id=category_id)
    
    if listing_type:
        query = query.filter_by(listing_type=listing_type)
    
    if condition:
        query = query.filter_by(condition=condition)
    
    if min_price is not None:
        query = query.filter(Listing.price >= min_price)
    
    if max_price is not None:
        query = query.filter(Listing.price <= max_price)
    
    if search_query:
        query = query.filter(
            (Listing.title.contains(search_query)) |
            (Listing.description.contains(search_query))
        )
    
    listings = query.all()
    
    listings_data = []
    for listing in listings:
        listings_data.append({
            "id": listing.id,
            "title": listing.title,
            "description": listing.description,
            "price": listing.price,
            "listing_type": listing.listing_type,
            "owner_id": listing.owner.id,
            "image_url": url_for('static', filename='uploads/listings/' + listing.images[0].filename) if listing.images else None
        })
    
    return jsonify(listings_data)

if __name__ == "__main__":
    app.run(debug=True)
