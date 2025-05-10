from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from sqlalchemy.ext.hybrid import hybrid_property
import json

db = SQLAlchemy()

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default="user")  # "user" or "admin"
    first_name = db.Column(db.String(50))
    last_name = db.Column(db.String(50))
    mobile = db.Column(db.String(20))
    gender = db.Column(db.String(10))
    address = db.Column(db.Text)
    city = db.Column(db.String(50))
    state = db.Column(db.String(50))
    zip_code = db.Column(db.String(20))
    country = db.Column(db.String(50))
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    profile_image = db.Column(db.String(255))
    is_online = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    reviews = db.relationship('Review', backref='user', lazy=True, cascade="all, delete-orphan")
    installments = db.relationship('Installment', backref='user', lazy=True, cascade="all, delete-orphan")
    # Relationships for chat messages
    sent_messages = db.relationship('ChatMessage', foreign_keys='ChatMessage.sender_id', backref='sender', lazy=True)
    received_messages = db.relationship('ChatMessage', foreign_keys='ChatMessage.receiver_id', backref='receiver', lazy=True)
    # Relationships for donations
    donations_made = db.relationship('Donation', foreign_keys='Donation.donor_id', backref='donor', lazy=True)
    donations_received = db.relationship('Donation', foreign_keys='Donation.recipient_id', backref='recipient', lazy=True)
    # Relationships for listings
    listings = db.relationship('Listing', backref='owner', lazy=True, cascade="all, delete-orphan")
    # Relationships for cart
    cart_items = db.relationship('CartItem', backref='user', lazy=True, cascade="all, delete-orphan")
    # Relationships for wishlist
    wishlist_items = db.relationship('WishlistItem', backref='user', lazy=True, cascade="all, delete-orphan")
    # Relationships for trades
    trades_initiated = db.relationship('Trade', foreign_keys='Trade.initiator_id', backref='initiator', lazy=True)
    trades_received = db.relationship('Trade', foreign_keys='Trade.receiver_id', backref='receiver', lazy=True)
    # Relationships for notifications
    notifications = db.relationship('Notification', backref='user', lazy=True, cascade="all, delete-orphan")
    # Relationships for user reviews
    reviews_given = db.relationship('UserReview', foreign_keys='UserReview.reviewer_id', backref='reviewer', lazy=True)
    reviews_received = db.relationship('UserReview', foreign_keys='UserReview.reviewed_id', backref='reviewed', lazy=True)

    @hybrid_property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

class Review(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    tags = db.Column(db.String(100))
    date = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class Installment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    purpose = db.Column(db.String(200), nullable=False)
    duration = db.Column(db.Integer, nullable=False)  # Duration in months
    income = db.Column(db.Float, nullable=False)
    employment_status = db.Column(db.String(50), nullable=False)
    employer = db.Column(db.String(100))
    status = db.Column(db.String(20), default="pending")  # pending, approved, rejected
    admin_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class ChatMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    message = db.Column(db.Text, nullable=False)
    message_type = db.Column(db.String(20), default="text")  # text, image, emoji
    media_url = db.Column(db.String(255))  # For image messages
    is_read = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Donation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    donor_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Can be null for admin donations
    item_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    condition = db.Column(db.String(50), nullable=False)
    image_filename = db.Column(db.String(255), nullable=True)  # Store the image filename
    status = db.Column(db.String(20), default="pending")  # pending, accepted, declined, completed
    is_admin_donation = db.Column(db.Boolean, default=False)  # Flag for admin donations
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Category(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)
    description = db.Column(db.Text)
    parent_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)
    
    # Self-referential relationship for subcategories
    subcategories = db.relationship('Category', backref=db.backref('parent', remote_side=[id]))
    # Relationship with listings
    listings = db.relationship('Listing', backref='category', lazy=True)

class Listing(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    condition = db.Column(db.String(50), nullable=False)  # New, Like New, Good, Fair, Poor
    price = db.Column(db.Float, nullable=True)  # Null if not for sale
    listing_type = db.Column(db.String(20), nullable=False)  # exchange, sale, loan, donation
    exchange_preferences = db.Column(db.Text)  # What the user wants in exchange
    loan_duration = db.Column(db.Integer)  # Duration in days if it's a loan
    is_active = db.Column(db.Boolean, default=True)
    views = db.Column(db.Integer, default=0)
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    location = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Foreign keys
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=False)
    
    # Relationships
    images = db.relationship('ListingImage', backref='listing', lazy=True, cascade="all, delete-orphan")
    cart_items = db.relationship('CartItem', backref='listing', lazy=True, cascade="all, delete-orphan")
    wishlist_items = db.relationship('WishlistItem', backref='listing', lazy=True, cascade="all, delete-orphan")
    trades = db.relationship('Trade', foreign_keys='Trade.listing_id', backref='listing', lazy=True)

class ListingImage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    is_primary = db.Column(db.Boolean, default=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=False)
    quantity = db.Column(db.Integer, default=1)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

class WishlistItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)

class Trade(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    initiator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=False)
    offered_listing_id = db.Column(db.Integer, db.ForeignKey('listing.id'), nullable=True)  # For exchanges
    trade_type = db.Column(db.String(20), nullable=False)  # purchase, exchange, loan
    status = db.Column(db.String(20), default="pending")  # pending, accepted, rejected, completed
    message = db.Column(db.Text)
    loan_return_date = db.Column(db.DateTime, nullable=True)  # For loans
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship for offered listing
    offered_listing = db.relationship('Listing', foreign_keys=[offered_listing_id], backref='offered_trades')

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    message = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50), nullable=False)  # chat, trade, listing, system
    related_id = db.Column(db.Integer)  # ID of related entity (listing, trade, etc.)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserReview(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reviewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    reviewed_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    trade_id = db.Column(db.Integer, db.ForeignKey('trade.id'), nullable=True)
    rating = db.Column(db.Integer, nullable=False)  # 1-5 stars
    comment = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationship with trade
    trade = db.relationship('Trade')
