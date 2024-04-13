from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import frozendict
from odoo.tools.misc import formatLang


class KsGlobalDiscountInvoice(models.Model):
    """ changing the model to account.move """
    _inherit = "account.move"

    ks_global_discount_type = fields.Selection(
        [("percent", "Percentage"), ("amount", "Amount")],
        string="Universal Discount Type",
        readonly=True,
        default="percent",
    )
    ks_global_discount_rate = fields.Float("Universal Discount Rate", readonly=True)
    ks_amount_discount = fields.Monetary(
        string="Universal Discount",
        readonly=True,
        compute="_compute_amount",
        store=True,
    )
    ks_enable_discount = fields.Boolean(compute='ks_verify_discount')
    ks_sales_discount_account_id = fields.Integer(compute='ks_verify_discount')
    ks_purchase_discount_account_id = fields.Integer(compute='ks_verify_discount')

    @api.depends('company_id.ks_enable_discount')
    def ks_verify_discount(self):
        for rec in self:
            rec.ks_enable_discount = rec.company_id.ks_enable_discount
            rec.ks_sales_discount_account_id = rec.company_id.ks_sales_discount_account.id
            rec.ks_purchase_discount_account_id = rec.company_id.ks_purchase_discount_account.id

    @api.depends(
        'line_ids.debit',
        'line_ids.credit',
        'line_ids.currency_id',
        'line_ids.amount_currency',
        'line_ids.amount_residual',
        'line_ids.amount_residual_currency',
        'line_ids.payment_id.state',
        'ks_global_discount_type',
        'ks_global_discount_rate')
    def _compute_amount(self):
        super(KsGlobalDiscountInvoice, self)._compute_amount()
        for rec in self:
            rec.ks_calculate_discount()
            sign = rec.move_type in ['in_refund', 'out_refund'] and -1 or 1
            # rec.amount_total_company_signed = rec.amount_total * sign
            rec.amount_total_signed = rec.amount_total * sign

    # @api.multi
    def ks_calculate_discount(self):
        for rec in self:
            if rec.ks_global_discount_type == "amount":
                rec.ks_amount_discount = rec.ks_global_discount_rate if rec.amount_untaxed > 0 else 0
            elif rec.ks_global_discount_type == "percent":
                if rec.ks_global_discount_rate != 0.0:
                    rec.ks_amount_discount = (rec.amount_untaxed + rec.amount_tax) * rec.ks_global_discount_rate / 100
                else:
                    rec.ks_amount_discount = 0
            elif not rec.ks_global_discount_type:
                rec.ks_global_discount_rate = 0
                rec.ks_amount_discount = 0
            rec.amount_total = rec.amount_tax + rec.amount_untaxed - rec.ks_amount_discount
            # rec.ks_update_universal_discount()

    @api.constrains('ks_global_discount_rate')
    def ks_check_discount_value(self):
        if self.ks_global_discount_type == "percent":
            if self.ks_global_discount_rate > 100 or self.ks_global_discount_rate < 0:
                raise ValidationError('You cannot enter percentage value greater than 100.')
        else:
            if self.ks_global_discount_rate < 0 or self.amount_untaxed < 0:
                raise ValidationError(
                    'You cannot enter discount amount greater than actual cost or value lower than 0.')

    @api.depends_context("lang")
    @api.depends(
        "invoice_line_ids.currency_rate",
        "invoice_line_ids.tax_base_amount",
        "invoice_line_ids.tax_line_id",
        "invoice_line_ids.price_total",
        "invoice_line_ids.price_subtotal",
        "invoice_payment_term_id",
        "partner_id",
        "currency_id",
        "ks_global_discount_rate",
        "ks_global_discount_type",
        "ks_amount_discount",
    )
    def _compute_tax_totals(self):
        super(KsGlobalDiscountInvoice, self)._compute_tax_totals()
        for move in self:
            if move.ks_enable_discount and move.tax_totals:
                move.tax_totals["ks_amount_discount"] = move.ks_amount_discount
                move.tax_totals["formatted_ks_amount_discount"] = formatLang(
                    self.env, move.ks_amount_discount, currency_obj=move.currency_id
                )
                move.tax_totals["ks_global_discount_rate"] = (
                    move.ks_global_discount_rate
                )
                move.tax_totals["ks_global_discount_type"] = (
                    move.ks_global_discount_type
                )

                move.tax_totals["amount_total"] = (
                    move.tax_totals["amount_total"]
                    - move.tax_totals["ks_amount_discount"]
                )
                move.tax_totals["formatted_amount_total"] = formatLang(
                    self.env,
                    move.tax_totals["amount_total"],
                    currency_obj=move.currency_id,
                )


class KsGlobalDiscountMoveLine(models.Model):
    """Changing the model to account.move.line"""

    _inherit = "account.move.line"

    @api.depends(
        "account_id",
        "company_id",
        "discount",
        "price_unit",
        "quantity",
        "move_id.ks_amount_discount",
        "move_id.ks_global_discount_rate",
        "move_id.ks_global_discount_type",
    )
    def _compute_discount_allocation_needed(self):
        ## Call super
        super(KsGlobalDiscountMoveLine, self)._compute_discount_allocation_needed()

        ## We will insert new discounts into this line. This is equivalent to distributing the discount across
        ## all the product lines of the move.
        num_product_lines = len(self.move_id.invoice_line_ids)
        if num_product_lines == 0 or self.move_id.currency_id.is_zero(
            self.move_id.ks_amount_discount
        ):
            return

        val_amount = self.move_id.ks_amount_discount / num_product_lines

        # check if sales or purchase and get account accordingly
        if self.move_id.move_type in ["out_invoice", "out_refund"]:
            discount_allocation_account = self.move_id.ks_sales_discount_account_id
        elif self.move_id.move_type in ["in_invoice", "in_refund"]:
            discount_allocation_account = self.move_id.ks_purchase_discount_account_id

        for line in self:
            if line.display_type != "product":
                continue

            discount_allocation_needed = {}
            discount_allocation_needed_vals = discount_allocation_needed.setdefault(
                frozendict(
                    {
                        "account_id": line.account_id.id,
                        "move_id": line.move_id.id,
                    }
                ),
                {
                    "display_type": "discount",
                    "name": _("Universal Discount"),
                    "amount_currency": 0.0,
                },
            )
            discount_allocation_needed_vals["amount_currency"] += (
                val_amount * line.move_id.direction_sign
            )
            discount_allocation_needed_vals = discount_allocation_needed.setdefault(
                frozendict(
                    {
                        "move_id": line.move_id.id,
                        "account_id": discount_allocation_account,
                    }
                ),
                {
                    "display_type": "discount",
                    "name": _("Universal Discount"),
                    "amount_currency": 0.0,
                },
            )
            discount_allocation_needed_vals["amount_currency"] -= (
                val_amount * line.move_id.direction_sign
            )

            ## Append to discount_allocation_needed
            if line.discount_allocation_needed:
                ## Since it is afrozen dict, we need to create a new dict that combines the two
                new_discount_allocation_needed = {}
                ## We iterate over the old dictionary in line.discount_allocation_needed and
                ## if the key is in the new dictionary discount_allocation_needed, we add the values
                ## of the two dictionaries together
                for k, v in line.discount_allocation_needed.items():
                    if k in discount_allocation_needed:
                        val = new_discount_allocation_needed.setdefault(
                            k,
                            {
                                "display_type": "discount",
                                "name": _("Universal Discount") + " - " + v["name"],
                                "amount_currency": 0.0,
                            },
                        )
                        val["amount_currency"] = (
                            v["amount_currency"]
                            + discount_allocation_needed[k]["amount_currency"]
                        )

                    else:
                        new_discount_allocation_needed[k] = v

                ## Now we need to add those lines in the new dictionary that are not in the old dictionary
                for k, v in discount_allocation_needed.items():
                    if k not in new_discount_allocation_needed:
                        new_discount_allocation_needed[k] = v

                ## Update the line
                line.discount_allocation_needed = {
                    k: frozendict(v) for k, v in new_discount_allocation_needed.items()
                }
            else:
                line.discount_allocation_needed = {
                    k: frozendict(v) for k, v in discount_allocation_needed.items()
                }
