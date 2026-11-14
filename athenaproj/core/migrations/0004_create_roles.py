from django.db import migrations


def create_roles(apps, schema_editor):
    Group = apps.get_model('auth', 'Group')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    content_type, _ = ContentType.objects.get_or_create(
        app_label='core', model='accessrights'
    )
    permission_labels = {
        'participant_access': 'Can access participant features',
        'panel_access': 'Can access the panel',
        'staff_access': 'Can access staff features',
        'admin_access': 'Can access admin features',
    }
    for codename, name in permission_labels.items():
        Permission.objects.get_or_create(
            content_type=content_type,
            codename=codename,
            defaults={'name': name},
        )
    permissions = {
        permission.codename: permission
        for permission in Permission.objects.filter(
            content_type=content_type,
            codename__in=[
                'participant_access',
                'panel_access',
                'staff_access',
                'admin_access',
            ],
        )
    }
    role_permissions = {
        'Participant': ['participant_access'],
        'Coordinator': ['panel_access'],
        'Staff': ['panel_access', 'staff_access'],
        'Admin': ['panel_access', 'staff_access', 'admin_access'],
    }
    for name, codenames in role_permissions.items():
        group, _ = Group.objects.get_or_create(name=name)
        group.permissions.set([permissions[codename] for codename in codenames])


def remove_roles(apps, schema_editor):
    apps.get_model('auth', 'Group').objects.filter(
        name__in=['Participant', 'Coordinator', 'Staff', 'Admin']
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0003_accessrights_notification_participantprofile_and_more'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [migrations.RunPython(create_roles, remove_roles)]
