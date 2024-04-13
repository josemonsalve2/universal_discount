# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import UserError, ValidationError
from odoo.tools.misc import formatLang


class KsGlobalDiscountSales(models.Model):
    _inherit = "sale.order"

    ks_global_discount_type = fields.Selection(
        [("percent", "Percentage"), ("amount", "Amount")],
        string="Universal Discount Type",
        readonly=True,
        default="percent",
    )
    ks_global_discount_rate = fields.Float(
        "Universal Discount Rate",
        readonly=True,
    )
    ks_amount_discount = fields.Monetary(
        string="Universal Discount",
        readonly=True,
        compute="_compute_amounts",
        store=True,
    )
    ks_enable_discount = fields.Boolean(compute='ks_verify_discount')

    @api.depends('company_id.ks_enable_discount')
    def ks_verify_discount(self):
        for rec in self:
            rec.ks_enable_discount = rec.company_id.ks_enable_discount

    @api.onchange("ks_global_discount_rate", "ks_global_discount_type")
    @api.depends(
        "order_line.price_total", "ks_global_discount_rate", "ks_global_discount_type"
    )
    def _compute_amounts(self):
        res = super(KsGlobalDiscountSales, self)._compute_amounts()
        for rec in self:
            rec.ks_calculate_discount()
        return res

    def _prepare_invoice(self):
        res = super(KsGlobalDiscountSales, self)._prepare_invoice()
        for rec in self:
            res['ks_global_discount_rate'] = rec.ks_global_discount_rate
            res['ks_global_discount_type'] = rec.ks_global_discount_type
        return res

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
                rec.ks_amount_discount = 0
                rec.ks_global_discount_rate = 0
            rec.amount_total = rec.amount_untaxed + rec.amount_tax - rec.ks_amount_discount

    @api.depends_context("lang")
    @api.depends(
        "order_line.tax_id",
        "order_line.price_unit",
        "amount_total",
        "amount_untaxed",
        "currency_id",
        "ks_global_discount_rate",
        "ks_global_discount_type",
        "ks_amount_discount",
    )
    def _compute_tax_totals(self):
        super(KsGlobalDiscountSales, self)._compute_tax_totals()
        for order in self:
            if order.ks_enable_discount and order.tax_totals:
                order.tax_totals["ks_amount_discount"] = order.ks_amount_discount
                order.tax_totals["formatted_ks_amount_discount"] = formatLang(
                    self.env, order.ks_amount_discount, currency_obj=order.currency_id
                )
                order.tax_totals["ks_global_discount_rate"] = (
                    order.ks_global_discount_rate
                )
                order.tax_totals["ks_global_discount_type"] = (
                    order.ks_global_discount_type
                )

                order.tax_totals["amount_total"] = (
                    order.tax_totals["amount_total"]
                    - order.tax_totals["ks_amount_discount"]
                )
                order.tax_totals["formatted_amount_total"] = formatLang(
                    self.env,
                    order.tax_totals["amount_total"],
                    currency_obj=order.currency_id,
                )

    @api.constrains('ks_global_discount_rate')
    def ks_check_discount_value(self):
        if self.ks_global_discount_type == "percent":
            if self.ks_global_discount_rate > 100 or self.ks_global_discount_rate < 0:
                raise ValidationError('You cannot enter percentage value greater than 100.')
        else:
            if self.ks_global_discount_rate < 0 or self.ks_global_discount_rate > self.amount_untaxed:
                raise ValidationError(
                    'You cannot enter discount amount greater than actual cost or value lower than 0.')


class KsSaleAdvancePaymentInv(models.TransientModel):
    _inherit = "sale.advance.payment.inv"

    def _create_invoice(self, order, so_line, amount):
        invoice = super(KsSaleAdvancePaymentInv, self)._create_invoice(order, so_line, amount)
        if invoice:
            invoice['ks_global_discount_rate'] = order.ks_global_discount_rate
            invoice['ks_global_discount_type'] = order.ks_global_discount_type
        return invoice
