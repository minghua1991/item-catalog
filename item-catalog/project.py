import httplib2
import json
import random
import requests
import string

from functools import wraps

from database_setup import Base, Category, Item, User

from flask import (Flask,
                   flash,
                   jsonify,
                   make_response,
                   render_template,
                   request,
                   redirect,
                   session as login_session,
                   url_for,)

from sqlalchemy import create_engine, asc, desc
from sqlalchemy.orm import sessionmaker

from oauth2client.client import flow_from_clientsecrets, FlowExchangeError


app = Flask(__name__)


# Get client id from the json file provided by google.
CLIENT_ID = json.loads(open("client_secrets.json",
                            "r").read())["web"]["client_id"]


APPLICATION_NAME = "Item Catalog App"


# Connect to Database and create database session
engine = create_engine("sqlite:///itemCatalog.db")
Base.metadata.bind = engine


DBSession = sessionmaker(bind=engine)
session = DBSession()


# Create anti-forgery state token
@app.route("/login")
def showLogin():
    """It randomly generate 32 chars to prevent CSRF."""
    state = "".join(random.choice(string.ascii_uppercase + string.digits)
                    for x in xrange(32))
    login_session["state"] = state
    return render_template("login.html", STATE=state)


@app.route("/gconnect", methods=["POST"])
def gconnect():
    """It will allow user to sign in the application with google account."""
    # Validate state token
    if request.args.get("state") != login_session["state"]:
        response = make_response(json.dumps("Invalid state parameter."), 401)
        response.headers["Content-Type"] = "application/json"
        return response

    # Obtain authorization code
    code = request.data

    try:
        # Upgrade the authorization code into a credentials object
        oauth_flow = flow_from_clientsecrets("client_secrets.json", scope="")
        oauth_flow.redirect_uri = "postmessage"
        credentials = oauth_flow.step2_exchange(code)
    except FlowExchangeError:
        response = make_response(
            json.dumps("Failed to upgrade the authorization code."), 401)
        response.headers["Content-Type"] = "application/json"
        return response

    # Check that the access token is valid.
    access_token = credentials.access_token
    url = ("https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=%s"
           % access_token)
    h = httplib2.Http()
    result = json.loads(h.request(url, "GET")[1])

    # If there was an error in the access token info, abort.
    if result.get("error") is not None:
        response = make_response(json.dumps(result.get("error")), 500)
        response.headers["Content-Type"] = "application/json"
        return response

    # Verify that the access token is used for the intended user.
    gplus_id = credentials.id_token["sub"]
    if result["user_id"] != gplus_id:
        response = make_response(
            json.dumps("Token's user ID doesn't match given user ID."), 401)
        response.headers["Content-Type"] = "application/json"
        return response

    # Verify that the access token is valid for this app.
    if result["issued_to"] != CLIENT_ID:
        response = make_response(
            json.dumps("Token's client ID does not match app's."), 401)
        print "Token's client ID does not match app's."
        response.headers["Content-Type"] = "application/json"
        return response

    stored_access_token = login_session.get("access_token")
    stored_gplus_id = login_session.get("gplus_id")
    if stored_access_token is not None and gplus_id == stored_gplus_id:
        response = make_response(json.dumps("This user's already connected."),
                                 200)
        response.headers["Content-Type"] = "application/json"
        return response

    # Store the access token in the session for later use.
    login_session["access_token"] = credentials.access_token
    login_session["gplus_id"] = gplus_id

    # Get user info
    userinfo_url = "https://www.googleapis.com/userinfo/v2/me"
    params = {"access_token": credentials.access_token, "alt": "json"}
    answer = requests.get(userinfo_url, params=params)

    data = answer.json()
    print answer.json()
    login_session["provider"] = "google"
    login_session["username"] = data["name"]
    login_session["picture"] = data["picture"]
    login_session["email"] = data["email"]

    # see if user exists, if it doesn"t make a new one
    user_id = getUserID(login_session["email"])
    if not user_id:
        user_id = createUser(login_session)
    login_session["user_id"] = user_id

    output = ""
    output += "<h1>Welcome, "
    output += login_session["username"]
    output += "!</h1>"
    output += "<img src='"
    output += login_session["picture"]
    output += ("""'style='width: 300px; height: 300px;border-radius: 150px;
               -webkit-border-radius: 150px;-moz-border-radius: 150px;'>""")
    flash("you are now logged in as %s" % login_session["username"])
    print "done!"
    return output


def getUserID(email):
    """It checks if the given email address is already in database.
    If yes, it will return the user id.
    """
    try:
        user = session.query(User).filter_by(email=email).one()
        return user.id
    except:
        return None


def getUserInfo(user_id):
    """It return the user object by checking the user id."""
    user = session.query(User).filter_by(id=user_id).one()
    return user


def createUser(login_session):
    """It checks if the user has stored in the database.
    If not, it will create a new one."""
    newUser = User(name=login_session["username"],
                   email=login_session["email"],
                   picture=login_session["picture"])
    session.add(newUser)
    session.commit()
    user = session.query(User).filter_by(email=login_session["email"]).one()
    return user.id


def login_required(f):
    """This checks whether the user has signed in or not"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "username" not in login_session:
            return redirect("/login")
        return f(*args, **kwargs)
    return decorated_function


# DISCONNECT - Revoke a current user's token and reset their login_session
@app.route("/gdisconnect")
def gdisconnect():
    """It will clear login_session when logging out google account"""
    access_token = login_session["access_token"]
    print "In gdisconnect access token is %s" % access_token
    print "User name is: "
    print login_session["username"]

    if access_token is None:
        print "Access Token is None"
        response = make_response(json.dumps("Current user not connected."),
                                 401)
        response.headers["Content-Type"] = "application/json"
        return response

    url = ("https://accounts.google.com/o/oauth2/revoke?token=%s"
           % login_session["access_token"])
    h = httplib2.Http()
    result = h.request(url, "GET")[0]
    print "result is "
    print result

    if result["status"] == "200":
        del login_session["access_token"]
        del login_session["gplus_id"]
        del login_session["username"]
        del login_session["user_id"]
        del login_session["email"]
        del login_session["picture"]

        response = make_response(json.dumps("Successfully disconnected."), 200)
        response.headers["Content-Type"] = "application/json"
        return response
    else:
        response = make_response(json.dumps("Failed to revoke user's token.",
                                 400))
        response.headers["Content-Type"] = "application/json"
        return response


@app.route("/fbconnect", methods=["POST"])
def fbconnect():
    """This allows users to use facebook account to sign in."""
    if request.args.get("state") != login_session["state"]:
        response = make_response(json.dumps("Invalid state parameter."), 401)
        response.headers["Content-Type"] = "application/json"
        return response
    access_token = request.data
    print "access token received %s " % access_token

    app_id = json.loads(open("fb_client_secrets.json",
                             "r").read())["web"]["app_id"]

    app_secret = json.loads(open("fb_client_secrets.json",
                                 "r").read())["web"]["app_secret"]

    url = ("https://graph.facebook.com/v2.8/oauth/access_token?"
           "grant_type=fb_exchange_token&client_id=%s&client_secret=%s"
           "&fb_exchange_token=%s") % (app_id, app_secret, access_token)

    h = httplib2.Http()
    result = h.request(url, "GET")[1]

    data = json.loads(result)
    token = data["access_token"]

    # Use token to get user info from API
    userinfo_url = "https://graph.facebook.com/v2.8/me"

    url = userinfo_url + "?access_token=%s&fields=name,id,email" % token
    h = httplib2.Http()
    result = h.request(url, "GET")[1]
    data = json.loads(result)
    print data

    login_session["provider"] = "facebook"
    login_session["username"] = data["name"]
    login_session["email"] = data["email"]
    login_session["facebook_id"] = data["id"]

    login_session["access_token"] = token

    # Get user picture
    url = userinfo_url + \
        "/picture?access_token=%s&redirect=0&height=200&width=200" % token
    h = httplib2.Http()
    result = h.request(url, "GET")[1]
    data = json.loads(result)

    login_session["picture"] = data["data"]["url"]

    # see if user exists
    user_id = getUserID(login_session["email"])
    if not user_id:
        user_id = createUser(login_session)
    login_session["user_id"] = user_id

    output = ""
    output += "<h1>Welcome, "
    output += login_session["username"]
    output += "!</h1>"
    output += "<img src='"
    output += login_session["picture"]
    output += ("""'style='width: 300px; height: 300px;border-radius: 150px;
               -webkit-border-radius: 150px;-moz-border-radius: 150px;'>""")
    flash("Now logged in as %s" % login_session["username"])
    return output


@app.route("/fbdisconnect")
def fbdisconnect():
    """It will clear login_session when logging out facebook account"""
    facebook_id = login_session["facebook_id"]
    # The access token must me included to successfully logout
    access_token = login_session["access_token"]
    url = ("https://graph.facebook.com/%s/permissions?access_token=%s"
           % (facebook_id, access_token))
    h = httplib2.Http()
    result = h.request(url, "DELETE")[1]

    del login_session["access_token"]
    del login_session["username"]
    del login_session["user_id"]
    del login_session["facebook_id"]
    del login_session["email"]
    del login_session["picture"]
    return "You have been logged out"


# Disconnect based on provider
@app.route("/disconnect")
def disconnect():
    """This is the logout function for facebook and google account"""
    if "provider" in login_session:
        if login_session["provider"] == "google":
            gdisconnect()
        if login_session["provider"] == "facebook":
            fbdisconnect()
        del login_session["provider"]
        flash("You have successfully been logged out.")
        return redirect(url_for("showCategories"))
    else:
        flash("You were not logged in")
        return redirect(url_for("showCategories"))


# View the whole database
@app.route("/category/JSON")
def categoriesJSON():
    categories = session.query(Category).all()
    serialized_categories = []
    for i in categories:
        new_serialized_category = i.serialize
        items = session.query(Item).filter_by(category_id=i.id).all()
        serialized_items = []
        for j in items:
            serialized_items.append(j.serialize)
        new_serialized_category["items"] = serialized_items
        serialized_categories.append(new_serialized_category)

    return jsonify(categories=serialized_categories)


# JSON APIs to view Category Information
@app.route("/category/<int:category_id>/item/JSON")
def categoryItemJSON(category_id):
    items = session.query(Item).filter_by(
        category_id=category_id).all()
    return jsonify(items=[i.serialize for i in items]), 200


# View a Item Information
@app.route("/category/<int:category_id>/item/<int:item_id>/JSON")
def itemJSON(category_id, item_id):
    item = session.query(Item).filter_by(id=item_id).one()
    return jsonify(item=item.serialize)


# View all users
@app.route("/user/JSON")
def userJSON():
    users = session.query(User).all()
    return jsonify(users=[i.serialize for i in users])


# Show all categories
@app.route("/")
@app.route("/category/")
def showCategories():
    categories = session.query(Category).order_by(desc(Category.id)).all()
    if "username" not in login_session:
        return render_template("publicCategories.html", categories=categories)
    else:
        return render_template("categories.html", categories=categories)


# Create a new category
@app.route("/category/new/", methods=["GET", "POST"])
@login_required
def newCategory():
    if request.method == "POST":
        newCategory = Category(
            name=request.form["name"], user_id=login_session["user_id"])
        session.add(newCategory)
        flash("New Category %s Successfully Created" % newCategory.name)
        session.commit()
        return redirect(url_for("showCategories"))
    else:
        return render_template("newCategory.html")


# Edit a category
@app.route("/category/<int:category_id>/edit/", methods=["GET", "POST"])
@login_required
def editCategory(category_id):
    editedCategory = session.query(
        Category).filter_by(id=category_id).one()
    if editedCategory.user_id != login_session["user_id"]:
        return "<script>function myFunction()\
                {alert('You are not authorized to edit this category.\
                Please create your own category in order to delete.');\
                window.location.href='/category/%s/';}\
                </script><body onload='myFunction()''>" % category_id
    if request.method == "POST":
        if request.form["name"]:
            editedCategory.name = request.form["name"]
            flash("Category Successfully Updated to %s" % editedCategory.name)
            return redirect(url_for("showCategories"))
    else:
        return render_template("editCategory.html", category=editedCategory)


# Delete a category
@app.route("/category/<int:category_id>/delete/", methods=["GET", "POST"])
@login_required
def deleteCategory(category_id):
    categoryToDelete = session.query(
        Category).filter_by(id=category_id).one()
    if categoryToDelete.user_id != login_session["user_id"]:
        return "<script>function myFunction()\
                {alert('You are not authorized to delete this category.\
                Please create your own category in order to delete.');\
                window.location.href='/category/%s/';}\
                </script><body onload='myFunction()''>" % category_id
    if request.method == "POST":
        session.delete(categoryToDelete)
        flash("%s Successfully Deleted" % categoryToDelete.name)
        session.commit()
        return redirect(url_for("showCategories"))
    else:
        return render_template("deleteCategory.html",
                               category=categoryToDelete)


# Show all items for a category
@app.route("/category/<int:category_id>/")
@app.route("/category/<int:category_id>/item/")
def showItems(category_id):
    category = session.query(Category).filter_by(id=category_id).one()
    creator = getUserInfo(category.user_id)
    items = session.query(Item).filter_by(
        category_id=category_id).order_by(desc('id')).all()

    # either one condition is true, the statement will be executed
    if ("username" not in login_session or
            creator.id != login_session["user_id"]):
        return render_template("publicItems.html",
                               items=items,
                               category=category,
                               creator=creator)
    else:
        return render_template("items.html",
                               items=items,
                               category=category,
                               creator=creator)


# Create a new item for a category
@app.route("/category/<int:category_id>/item/new/", methods=["GET", "POST"])
@login_required
def newItem(category_id):
    category = session.query(Category).filter_by(id=category_id).one()
    if login_session["user_id"] != category.user_id:
        return "<script>function myFunction()\
                {alert('You are not authorized to add items to this category.\
                Please create your own category in order to add items.');\
                window.location.href='/category/%s/';}\
                </script><body onload='myFunction()''>" % category_id
    if request.method == "POST":
        newItem = Item(name=request.form["name"],
                       category_id=category_id,
                       user_id=category.user_id)
        session.add(newItem)
        session.commit()
        flash("New Item %s Successfully Created" % (newItem.name))
        return redirect(url_for("showItems", category_id=category_id))
    else:
        return render_template("newItem.html", category_id=category_id)


# Edit a item
@app.route("/category/<int:category_id>/item/<int:item_id>/edit",
           methods=["GET", "POST"])
@login_required
def editItem(category_id, item_id):
    editedItem = session.query(Item).filter_by(id=item_id).one()
    category = session.query(Category).filter_by(id=category_id).one()
    if login_session["user_id"] != category.user_id:
        return "<script>function myFunction()\
                {alert('You are not authorized to edit items to this category.\
                Please create your own category in order to edit items.');\
                window.location.href='/category/%s/';}\
                </script><body onload='myFunction()''>" % category_id
    if request.method == "POST":
        if request.form["name"]:
            editedItem.name = request.form["name"]
        session.add(editedItem)
        session.commit()
        flash("Item Successfully Updated to %s" % editedItem.name)
        return redirect(url_for("showItems", category_id=category_id))
    else:
        return render_template("editItem.html",
                               category_id=category_id,
                               item_id=item_id,
                               item=editedItem)


# Delete a item
@app.route("/category/<int:category_id>/item/<int:item_id>/delete",
           methods=["GET", "POST"])
@login_required
def deleteItem(category_id, item_id):
    category = session.query(Category).filter_by(id=category_id).one()
    itemToDelete = session.query(Item).filter_by(id=item_id).one()
    if login_session["user_id"] != category.user_id:
        return "<script>function myFunction()\
                {alert('You are not authorized to delete items from category.\
                Please create your own category in order to delete items.');\
                window.location.href='/category/%s/';}\
                </script><body onload='myFunction()''>" % category_id
    if request.method == "POST":
        session.delete(itemToDelete)
        session.commit()
        flash("Item Successfully Deleted")
        return redirect(url_for("showItems", category_id=category_id))
    else:
        return render_template("deleteItem.html",
                               item=itemToDelete,
                               category=category)


if __name__ == "__main__":
    app.secret_key = "super_secret_key"
    app.debug = True
    app.run(host="0.0.0.0", port=8080)
