from app import main_create
from app import db
from app.models import User
app=main_create()
with app.app_context():
    db.create_all()
    print("Done")

if __name__=='__main__':
    app.run(debug=True)
    #app.run(host="0.0.0.0", port=5000,debug=True)