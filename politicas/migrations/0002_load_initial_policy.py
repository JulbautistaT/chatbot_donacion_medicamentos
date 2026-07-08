import os
from django.db import migrations
from django.conf import settings

def load_initial_policy(apps, schema_editor):
    PoliticaDatos = apps.get_model('politicas', 'PoliticaDatos')
    
    # Path to templates/politica_v1.html
    policy_path = os.path.join(settings.BASE_DIR, 'templates', 'politica_v1.html')
    
    if os.path.exists(policy_path):
        with open(policy_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Update or create the active policy version 1.0
        PoliticaDatos.objects.update_or_create(
            version='1.0',
            defaults={
                'titulo': 'Política de Tratamiento de Datos Personales',
                'contenido_html': content,
                'fecha_vigencia': '2026-06-11',
                'es_activa': True
            }
        )

def unload_initial_policy(apps, schema_editor):
    PoliticaDatos = apps.get_model('politicas', 'PoliticaDatos')
    PoliticaDatos.objects.filter(version='1.0').delete()

class Migration(migrations.Migration):

    dependencies = [
        ('politicas', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(load_initial_policy, unload_initial_policy),
    ]
