from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("borrowing", "0002_borrowingrequest_cancelled_at_and_more")]
    operations = [migrations.AddField(
        model_name="borrowingrequest", name="approval_reason",
        field=models.TextField(blank=True, max_length=300),
    )]
