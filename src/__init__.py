from .app import app, CONFIG
from . import routes # This will ensure routes are registered

# You might not need to explicitly define __all__ if you're running the app differently
# __all__ = ['app', 'CONFIG']

def main():
    """Main function to run the Flask app."""
    # Import routes here if not already imported, to ensure they are registered
    # from . import routes 
    app.run(
        host=CONFIG['host'],
        port=CONFIG['port'],
        debug=True # Set to False in production
    )

if __name__ == '__main__':
    main()