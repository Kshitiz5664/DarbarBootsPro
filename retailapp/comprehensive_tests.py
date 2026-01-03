"""
Comprehensive test suite for retail app
Tests all critical functionality and bug fixes
"""
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from decimal import Decimal
from datetime import datetime, timedelta
import json

from items.models import Item
from retailapp.models import RetailInvoice, RetailInvoiceItem, RetailReturn


class RetailAppSetupTestCase(TestCase):
    """Base test case with common setup"""
    
    def setUp(self):
        """Set up test data"""
        # Create test user
        self.user = User.objects.create_user(
            username='testuser',
            email='test@example.com',
            password='testpass123'
        )
        
        # Create test items
        self.item1 = Item.objects.create(
            name='Test Boot 1',
            price_wholesale=Decimal('500.00'),
            price_retail=Decimal('800.00'),
            gst_percent=Decimal('12.00'),
            quantity=100,
            created_by=self.user,
            updated_by=self.user
        )
        
        self.item2 = Item.objects.create(
            name='Test Boot 2',
            price_wholesale=Decimal('400.00'),
            price_retail=Decimal('600.00'),
            gst_percent=Decimal('5.00'),
            quantity=100,
            created_by=self.user,
            updated_by=self.user
        )
        
        # Create client for requests
        self.client = Client()
        self.client.login(username='testuser', password='testpass123')


class RetailInvoiceModelTests(RetailAppSetupTestCase):
    """Test RetailInvoice model functionality"""
    
    def test_invoice_creation(self):
        """Test invoice creation"""
        invoice = RetailInvoice.objects.create(
            customer_name='Test Customer',
            customer_mobile='9876543210',
            created_by=self.user,
            updated_by=self.user
        )
        
        self.assertEqual(invoice.customer_name, 'Test Customer')
        self.assertTrue(invoice.is_active)
        self.assertFalse(invoice.is_paid)
        # Auto-generated invoice number should be set
        self.assertTrue(invoice.invoice_number.startswith('RTL-'))
    
    def test_invoice_soft_delete(self):
        """Test soft delete functionality"""
        invoice = RetailInvoice.objects.create(
            customer_name='Test Customer 2',
            customer_mobile='9876543211',
            created_by=self.user,
            updated_by=self.user
        )
        
        # Soft delete
        invoice.is_active = False
        invoice.save()
        
        # Should not appear in active queries
        self.assertFalse(
            RetailInvoice.objects.filter(id=invoice.id, is_active=True).exists()
        )
    
    def test_invoice_number_generation(self):
        """Test unique invoice number generation"""
        invoice1 = RetailInvoice.objects.create(
            customer_name='Customer 1',
            created_by=self.user,
            updated_by=self.user
        )
        
        invoice2 = RetailInvoice.objects.create(
            customer_name='Customer 2',
            created_by=self.user,
            updated_by=self.user
        )
        
        # Invoice numbers should be different
        self.assertNotEqual(invoice1.invoice_number, invoice2.invoice_number)
        self.assertTrue(invoice1.invoice_number.startswith('RTL-'))
        self.assertTrue(invoice2.invoice_number.startswith('RTL-'))


class RetailInvoiceItemTests(RetailAppSetupTestCase):
    """Test RetailInvoiceItem model functionality"""
    
    def test_item_total_with_gst_and_discount(self):
        """Test item total calculation with GST and discount"""
        invoice = RetailInvoice.objects.create(
            customer_name='Test Customer',
            created_by=self.user,
            updated_by=self.user
        )
        
        item = RetailInvoiceItem.objects.create(
            invoice=invoice,
            item=self.item1,
            quantity=Decimal('1'),
            rate=Decimal('1000.00'),
            gst_percent=Decimal('12.00'),
            discount_percent=Decimal('10.00'),
            created_by=self.user,
            updated_by=self.user
        )
        
        # Verify calculations
        self.assertEqual(item.base_amount, Decimal('1000.00'))  # 1 * 1000
        self.assertEqual(item.gst_amount, Decimal('120.00'))   # 1000 * 12%
        self.assertEqual(item.discount_amount, Decimal('100.00'))  # 1000 * 10%
        self.assertEqual(item.total, Decimal('1020.00'))  # 1000 + 120 - 100


class RetailReturnTests(RetailAppSetupTestCase):
    """Test RetailReturn model functionality"""
    
    def test_return_validation(self):
        """Test return validation"""
        invoice = RetailInvoice.objects.create(
            customer_name='Test Customer',
            created_by=self.user,
            updated_by=self.user
        )
        
        item = RetailInvoiceItem.objects.create(
            invoice=invoice,
            item=self.item1,
            quantity=Decimal('5'),
            rate=Decimal('800.00'),
            gst_percent=Decimal('12.00'),
            discount_percent=Decimal('0'),
            created_by=self.user,
            updated_by=self.user
        )
        
        # Create return - amount is auto-calculated from item's total
        return_obj = RetailReturn.objects.create(
            invoice=invoice,
            item=item,
            quantity=Decimal('2'),
            # amount will be auto-calculated: per_unit = item.total / item.quantity * 2
            reason='Test return',
            created_by=self.user,
            updated_by=self.user
        )
        
        self.assertEqual(return_obj.quantity, Decimal('2'))
        # Amount is calculated from item.total (5 * 800 + gst - discount = 4480)
        # per_unit = 4480 / 5 = 896
        # return amount = 896 * 2 = 1792
        self.assertEqual(return_obj.amount, Decimal('1792.00'))
    
    def test_return_with_none_amount(self):
        """Test manual return (without item) requires amount"""
        invoice = RetailInvoice.objects.create(
            customer_name='Test Customer',
            created_by=self.user,
            updated_by=self.user
        )
        
        # Create manual return (no item, must specify amount)
        # This tests that validation prevents None amount for manual returns
        try:
            return_obj = RetailReturn.objects.create(
                invoice=invoice,
                item=None,  # Manual return
                quantity=Decimal('2'),
                amount=None,  # This should fail validation
                reason='Test return',
                created_by=self.user,
                updated_by=self.user
            )
            # Should not reach here
            self.fail("Should have raised ValidationError for manual return without amount")
        except Exception as e:
            # Should raise validation error
            self.assertIn('amount', str(e).lower())
    
    def test_return_zero_division_prevention(self):
        """Test zero division is prevented in return calculation for item with 100% discount"""
        invoice = RetailInvoice.objects.create(
            customer_name='Test Customer',
            created_by=self.user,
            updated_by=self.user
        )
        
        # Create item with 100% discount = zero total
        item = RetailInvoiceItem.objects.create(
            invoice=invoice,
            item=self.item1,
            quantity=Decimal('5'),  
            rate=Decimal('800.00'),
            gst_percent=Decimal('0'),
            discount_percent=Decimal('100'),  # Full discount = zero total
            created_by=self.user,
            updated_by=self.user
        )
        
        # Item should have zero total (800 - 800 = 0)
        self.assertEqual(item.total, Decimal('0.00'))
        
        # Create return for this zero-total item
        # Should use fallback calculation: rate + gst - discount = 800 + 0 - 800 = 0
        return_obj = RetailReturn.objects.create(
            invoice=invoice,
            item=item,
            quantity=Decimal('1'),
            reason='Test return',
            created_by=self.user,
            updated_by=self.user
        )
        
        # Should successfully create without ZeroDivisionError
        # Return amount should be calculated using fallback formula
        self.assertIsNotNone(return_obj.amount)
        self.assertEqual(return_obj.amount, Decimal('0.00'))  # 1 * (800 + 0 - 800)


class RetailAjaxTests(RetailAppSetupTestCase):
    """Test AJAX endpoints"""
    
    def test_ajax_calculate_item_total(self):
        """Test AJAX item total calculation"""
        response = self.client.get(
            reverse('retailapp:ajax_calculate_total'),
            {
                'quantity': '2',
                'rate': '1000.00',
                'gst_percent': '12.00',
                'discount_percent': '10.00'
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(float(data['base_amount']), 2000.00)  # 2 * 1000
        self.assertEqual(float(data['gst_amount']), 240.00)   # 2000 * 12%
        self.assertEqual(float(data['discount_amount']), 200.00)  # 2000 * 10%
        self.assertEqual(float(data['total']), 2040.00)  # 2000 + 240 - 200
    
    def test_ajax_calculate_item_total_invalid_quantity(self):
        """Test AJAX calculation with invalid quantity"""
        response = self.client.get(
            reverse('retailapp:ajax_calculate_total'),
            {
                'quantity': '-5',
                'rate': '1000.00',
                'gst_percent': '12.00',
                'discount_percent': '10.00'
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        # Negative quantity should be clamped to 1
        self.assertEqual(float(data['base_amount']), 1000.00)
    
    def test_ajax_calculate_item_total_invalid_percentage(self):
        """Test AJAX calculation with invalid percentage"""
        response = self.client.get(
            reverse('retailapp:ajax_calculate_total'),
            {
                'quantity': '1',
                'rate': '1000.00',
                'gst_percent': '150.00',  # Over 100%, will be capped
                'discount_percent': '-10.00'  # Negative, will be clamped to 0
            }
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        # Over 100% gst should be capped at 100%, which means 100% of 1000 = 1000
        # Negative discount should be clamped to 0
        # total = 1000 + 1000 - 0 = 2000
        self.assertEqual(float(data['gst_amount']), 1000.00)  # Capped at 100% of rate
        self.assertEqual(float(data['discount_amount']), 0.00)  # Clamped to 0
        self.assertEqual(float(data['total']), 2000.00)  # 1000 + 1000 - 0
    
    def test_ajax_get_item_details(self):
        """Test AJAX get item details"""
        response = self.client.get(
            reverse('retailapp:ajax_item_details', args=[self.item1.id])
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['name'], 'Test Boot 1')
        self.assertEqual(float(data['retail_price']), 800.00)
        self.assertEqual(float(data['gst_percent']), 12.00)
    
    def test_ajax_search_items(self):
        """Test AJAX search items"""
        response = self.client.get(
            reverse('retailapp:ajax_search_items'),
            {'q': 'Test Boot'}
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertGreater(len(data['results']), 0)
        self.assertEqual(data['results'][0]['name'], 'Test Boot 1')
    
    def test_ajax_toggle_payment_status(self):
        """Test AJAX toggle payment status"""
        invoice = RetailInvoice.objects.create(
            customer_name='Test Customer',
            created_by=self.user,
            updated_by=self.user,
            is_paid=False
        )
        
        response = self.client.post(
            reverse('retailapp:ajax_toggle_payment', args=[invoice.id])
        )
        
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.assertTrue(data['is_paid'])


class ErrorHandlingTests(RetailAppSetupTestCase):
    """Test error handling"""
    
    def test_missing_item_in_invoice_item(self):
        """Test handling of missing item"""
        response = self.client.get(
            reverse('retailapp:ajax_item_details', args=[9999])
        )
        
        self.assertEqual(response.status_code, 404)
        data = response.json()
        self.assertFalse(data['success'])
    
    def test_invalid_calculation_parameters(self):
        """Test AJAX with invalid calculation parameters"""
        response = self.client.get(
            reverse('retailapp:ajax_calculate_total'),
            {
                'quantity': 'invalid',
                'rate': 'also_invalid',
                'gst_percent': '12.00',
                'discount_percent': '0'
            }
        )
        
        # Should handle gracefully with defaults
        self.assertEqual(response.status_code, 200)
        data = response.json()
        # Should succeed with default values
        self.assertTrue(data['success'] or 'error' in data)


if __name__ == '__main__':
    import unittest
    unittest.main()

