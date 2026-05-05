from django.shortcuts import render, get_object_or_404
from politicas.models import PoliticaDatos  
from anuncios.models import Anuncio

def politica_datos(request):
    politica = get_object_or_404(PoliticaDatos, es_activa=True)
    return render(request, 'politica_datos.html', {'politica': politica})

def anuncios_disponibles(request):
    anuncios = Anuncio.objects.filter(
        activo=True
    ).select_related('medicamento')

    return render(
        request,
        'anuncios.html',
        {'anuncios': anuncios}
    )