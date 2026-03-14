from flask import Blueprint, request, render_template
from flask_login import login_required
from utils.decorators import admin_required

bp = Blueprint('estoque_inicial_global', __name__, url_prefix='/estoque-inicial')

@bp.route('/', methods=['GET'])
@login_required
@admin_required
def list_entries():
    """ List and filter by cliente_id """  
    # Logic to filter and list entries from estoque_inicial_global table would go here
    return render_template('estoque_inicial_global/index.html')

@bp.route('/novo', methods=['GET', 'POST'])
@login_required
@admin_required
def create_entry():
    """ Create new initial stock entry """  
    if request.method == 'POST':
        # Validate required fields and unique constraint logic goes here
        pass  
    # Load allowed empresas and products for the form
    return render_template('estoque_inicial_global/novo.html')