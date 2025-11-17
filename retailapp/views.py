from django.shortcuts import render

# Create your views here.
# retail/views.py
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.views.generic import DetailView
from django.urls import reverse
from django.contrib import messages
from django.db import transaction
from django.http import HttpResponse

from .models import RetailInvoice, RetailInvoiceItem, RetailReturn
from .forms import RetailInvoiceForm, RetailInvoiceItemForm, RetailReturnForm

from django.template.loader import render_to_string
import tempfile

# Optional: PDF libs (weasyprint recommended). We'll detect availability.
try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except Exception:
    WEASYPRINT_AVAILABLE = False


class RetailBillingConsoleView(View):
    """Single-page billing console (list + create + manage)."""

    template_name = "retailapp/console.html"

    def get(self, request):
        invoices = RetailInvoice.objects.filter(is_active=True).order_by("-date", "-id")[:200]
        invoice_form = RetailInvoiceForm()
        item_form = RetailInvoiceItemForm()
        return_form = RetailReturnForm()

        # Determine which invoice is active (via URL ?active=ID)
        active_id = request.GET.get("active")
        if active_id:
            active_invoice = RetailInvoice.objects.filter(pk=active_id, is_active=True).first()
        else:
            active_invoice = invoices.first()

        # FILTERED QUERYSETS (templates cannot call .filter)
        active_items = active_invoice.retail_items.filter(is_active=True) if active_invoice else []
        active_returns = active_invoice.retail_returns.filter(is_active=True) if active_invoice else []

        context = {
            "invoices": invoices,
            "invoice_form": invoice_form,
            "item_form": item_form,
            "return_form": return_form,
            "active_invoice": active_invoice,

            # Add filtered lists here:
            "active_items": active_items,
            "active_returns": active_returns,
        }

        return render(request, self.template_name, context)


class RetailInvoiceCreateView(View):
    @transaction.atomic
    def post(self, request):
        form = RetailInvoiceForm(request.POST)
        if form.is_valid():
            inv = form.save(commit=False)
            inv.created_by = request.user
            inv.updated_by = request.user
            inv.save()
            messages.success(request, "Invoice created; you can now add items.")
            return redirect("retailapp:billing_console")
        messages.error(request, "Failed to create invoice. Check input.")
        return redirect("retailapp:billing_console")


class RetailInvoiceDetailView(DetailView):
    model = RetailInvoice
    template_name = "retailapp/invoice_detail.html"  # for direct viewing (not required for console)
    context_object_name = "invoice"


class RetailInvoiceUpdateView(View):
    @transaction.atomic
    def post(self, request, pk):
        inv = get_object_or_404(RetailInvoice, pk=pk)
        form = RetailInvoiceForm(request.POST, instance=inv)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, "Invoice updated.")
        else:
            messages.error(request, "Failed to update invoice.")
        return redirect("retailapp:billing_console")


class RetailInvoiceDeleteView(View):
    def get(self, request, pk):
        inv = get_object_or_404(RetailInvoice, pk=pk)
        inv.is_active = False
        inv.save()
        messages.success(request, "Invoice marked inactive.")
        return redirect("retailapp:billing_console")


class RetailInvoiceItemCreateView(View):
    def post(self, request, invoice_id):
        invoice = get_object_or_404(RetailInvoice, pk=invoice_id)
        form = RetailInvoiceItemForm(request.POST, invoice=invoice)
        if form.is_valid():
            item = form.save(commit=False)
            item.invoice = invoice
            item.created_by = request.user
            item.updated_by = request.user
            item.save()
            messages.success(request, "Item added.")
        else:
            messages.error(request, "Failed to add item: " + "; ".join(sum([list(e) for e in form.errors.values()], [])))
        return redirect("retailapp:billing_console")


class RetailInvoiceItemUpdateView(View):
    def post(self, request, pk):
        item = get_object_or_404(RetailInvoiceItem, pk=pk)
        form = RetailInvoiceItemForm(request.POST, instance=item, invoice=item.invoice)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, "Item updated.")
        else:
            messages.error(request, "Failed to update item.")
        return redirect("retailapp:billing_console")


class RetailInvoiceItemDeleteView(View):
    def get(self, request, pk):
        item = get_object_or_404(RetailInvoiceItem, pk=pk)
        item.is_active = False
        item.save()
        messages.success(request, "Item removed.")
        return redirect("retailapp:billing_console")


class RetailReturnCreateView(View):
    def post(self, request, invoice_id):
        invoice = get_object_or_404(RetailInvoice, pk=invoice_id)
        form = RetailReturnForm(request.POST, request.FILES, invoice=invoice)
        if form.is_valid():
            ret = form.save(commit=False)
            ret.invoice = invoice
            ret.created_by = request.user
            ret.updated_by = request.user
            ret.save()
            messages.success(request, "Return recorded.")
        else:
            messages.error(request, "Failed to record return.")
        return redirect("retailapp:billing_console")


class RetailReturnUpdateView(View):
    def post(self, request, pk):
        ret = get_object_or_404(RetailReturn, pk=pk)
        form = RetailReturnForm(request.POST, request.FILES, instance=ret, invoice=ret.invoice)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.updated_by = request.user
            obj.save()
            messages.success(request, "Return updated.")
        else:
            messages.error(request, "Failed to update return.")
        return redirect("retailapp:billing_console")


class RetailReturnDeleteView(View):
    def get(self, request, pk):
        ret = get_object_or_404(RetailReturn, pk=pk)
        ret.is_active = False
        ret.save()
        messages.success(request, "Return removed.")
        return redirect("retailapp:billing_console")


class RetailInvoicePDFView(View):
    """
    Render invoice as a PDF. Uses WeasyPrint when available; otherwise returns HTML.
    """

    def get(self, request, pk):
        invoice = get_object_or_404(RetailInvoice, pk=pk)
        items = invoice.retail_items.filter(is_active=True)
        returns = invoice.retail_returns.filter(is_active=True)

        html = render_to_string("retailapp/pdf_invoice.html", {"invoice": invoice, "items": items, "returns": returns, "request": request})

        if WEASYPRINT_AVAILABLE:
            html_obj = HTML(string=html, base_url=request.build_absolute_uri("/"))
            css = CSS(string="""
              @page { size: A4; margin: 20mm; }
              body { font-family: "Helvetica", "Arial", sans-serif; font-size: 12px; }
            """)
            result = html_obj.write_pdf(stylesheets=[css])
            response = HttpResponse(result, content_type="application/pdf")
            response["Content-Disposition"] = f'inline; filename="{invoice.invoice_number}.pdf"'
            return response

        # fallback: return HTML (developer can install weasyprint)
        return HttpResponse(html)
