from django.shortcuts import render, get_object_or_404  # pylint: disable=import-error
from .models import PoliticaDatos

def politica_datos(request):
    politica = get_object_or_404(PoliticaDatos, es_activa=True)
    return render(request, 'politica_datos.html', {'politica': politica})
