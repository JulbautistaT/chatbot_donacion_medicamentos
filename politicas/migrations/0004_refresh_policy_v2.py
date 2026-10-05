import os
from django.db import migrations
from django.conf import settings

def refresh_policy_v2(apps, schema_editor):
    """Vuelve a cargar templates/politica_v2.html en la versión 2.0 ya creada por 0003
    (corrección de la dirección del responsable); no cambia cuál política está activa."""
    PoliticaDatos = apps.get_model('politicas', 'PoliticaDatos')

    policy_path = os.path.join(settings.BASE_DIR, 'templates', 'politica_v2.html')

    if os.path.exists(policy_path):
        with open(policy_path, 'r', encoding='utf-8') as f:
            content = f.read()

        PoliticaDatos.objects.filter(version='2.0').update(contenido_html=content)

class Migration(migrations.Migration):

    dependencies = [
        ('politicas', '0003_load_policy_v2'),
    ]

    operations = [
        migrations.RunPython(refresh_policy_v2, migrations.RunPython.noop),
    ]
