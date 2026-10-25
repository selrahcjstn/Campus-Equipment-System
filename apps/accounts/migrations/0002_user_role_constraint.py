from django.db import migrations, models


def validate_existing_roles(apps, schema_editor):
    users = apps.get_model("accounts", "User").objects.using(schema_editor.connection.alias)
    if users.exclude(role__in=["BASIC_USER", "ADMIN"]).exists():
        raise RuntimeError(
            "Unsupported account roles exist. Review those accounts and explicitly "
            "assign BASIC_USER or ADMIN before retrying migration. No roles were changed."
        )


class Migration(migrations.Migration):
    dependencies = [("accounts", "0001_initial")]
    operations = [
        migrations.RunPython(validate_existing_roles, migrations.RunPython.noop),
        migrations.AddConstraint(model_name="user", constraint=models.CheckConstraint(
            condition=models.Q(role__in=["BASIC_USER", "ADMIN"]), name="accounts_valid_campus_role",
        )),
    ]
