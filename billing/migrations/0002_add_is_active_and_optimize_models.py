# Generated migration to add is_active field and optimize models

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0001_initial'),
    ]

    operations = [
        # Ensure all models inherit is_active from SoftDeleteMixin
        # This migration is primarily for documentation purposes
        # As SoftDeleteMixin should already provide is_active field
        
        # Add database constraints for better data integrity
        migrations.RunSQL(
            sql="""
            ALTER TABLE billing_invoice ADD CONSTRAINT check_base_amount_positive 
            CHECK (base_amount >= 0);
            """,
            reverse_sql="ALTER TABLE billing_invoice DROP CONSTRAINT check_base_amount_positive;",
            state_operations=[],
        ),
        
        migrations.RunSQL(
            sql="""
            ALTER TABLE billing_payment ADD CONSTRAINT check_payment_amount_positive 
            CHECK (amount > 0);
            """,
            reverse_sql="ALTER TABLE billing_payment DROP CONSTRAINT check_payment_amount_positive;",
            state_operations=[],
        ),
        
        migrations.RunSQL(
            sql="""
            ALTER TABLE billing_return ADD CONSTRAINT check_return_amount_positive 
            CHECK (amount > 0);
            """,
            reverse_sql="ALTER TABLE billing_return DROP CONSTRAINT check_return_amount_positive;",
            state_operations=[],
        ),
        
        migrations.RunSQL(
            sql="""
            ALTER TABLE billing_invoiceitem ADD CONSTRAINT check_quantity_positive 
            CHECK (quantity > 0);
            """,
            reverse_sql="ALTER TABLE billing_invoiceitem DROP CONSTRAINT check_quantity_positive;",
            state_operations=[],
        ),
        
        # Create indexes for better query performance
        migrations.RunSQL(
            sql="""
            CREATE INDEX billing_invoice_party_date_idx 
            ON billing_invoice(party_id, date);
            """,
            reverse_sql="DROP INDEX billing_invoice_party_date_idx;",
            state_operations=[],
        ),
        
        migrations.RunSQL(
            sql="""
            CREATE INDEX billing_payment_party_date_idx 
            ON billing_payment(party_id, date);
            """,
            reverse_sql="DROP INDEX billing_payment_party_date_idx;",
            state_operations=[],
        ),
        
        migrations.RunSQL(
            sql="""
            CREATE INDEX billing_invoiceitem_invoice_id_idx 
            ON billing_invoiceitem(invoice_id);
            """,
            reverse_sql="DROP INDEX billing_invoiceitem_invoice_id_idx;",
            state_operations=[],
        ),
        
        migrations.RunSQL(
            sql="""
            CREATE INDEX billing_return_invoice_id_idx 
            ON billing_return(invoice_id);
            """,
            reverse_sql="DROP INDEX billing_return_invoice_id_idx;",
            state_operations=[],
        ),
        
        migrations.RunSQL(
            sql="""
            CREATE INDEX billing_challan_party_date_idx 
            ON billing_challan(party_id, date);
            """,
            reverse_sql="DROP INDEX billing_challan_party_date_idx;",
            state_operations=[],
        ),
    ]
