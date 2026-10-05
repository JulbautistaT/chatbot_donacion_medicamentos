import os
from django.db import migrations
from django.conf import settings

def load_policy_v2(apps, schema_editor):
    PoliticaDatos = apps.get_model('politicas', 'PoliticaDatos')

    # Path to templates/politica_v2.html
    policy_path = os.path.join(settings.BASE_DIR, 'templates', 'politica_v2.html')

    if os.path.exists(policy_path):
        with open(policy_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # El modelo histórico no ejecuta PoliticaDatos.save(), así que la
        # desactivación de las demás versiones se hace aquí a mano.
        PoliticaDatos.objects.filter(es_activa=True).exclude(version='2.0').update(es_activa=False)
        PoliticaDatos.objects.update_or_create(
            version='2.0',
            defaults={
                'titulo': 'Política de Tratamiento de Datos Personales y Términos y Condiciones',
                'contenido_html': content,
                'fecha_vigencia': '2026-10-05',
                'es_activa': True
            }
        )

def unload_policy_v2(apps, schema_editor):
    PoliticaDatos = apps.get_model('politicas', 'PoliticaDatos')
    if PoliticaDatos.objects.filter(version='2.0').exists():
        PoliticaDatos.objects.filter(version='2.0').delete()
        PoliticaDatos.objects.filter(version='1.0').update(es_activa=True)

class Migration(migrations.Migration):

    dependencies = [
        ('politicas', '0002_load_initial_policy'),
    ]

    operations = [
        migrations.RunPython(load_policy_v2, unload_policy_v2),
    ]
