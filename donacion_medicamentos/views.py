from django.shortcuts import render, get_object_or_404
from politicas.models import PoliticaDatos  # ← nuevo import

def politica_datos(request):
    politica = get_object_or_404(PoliticaDatos, es_activa=True)
    return render(request, 'politica_datos.html', {'politica': politica})
