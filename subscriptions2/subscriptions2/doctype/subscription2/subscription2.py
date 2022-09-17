# Copyright (c) 2022 Richard Case
# For license information, please see license.txt


from datetime import datetime
from typing import Dict, List, Optional, Union

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils.data import (
	add_days,
	add_to_date,
	date_diff,
	get_last_day,
	get_year_ending,
	getdate,
	nowdate,
)

from erpnext import get_default_cost_center
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions
from erpnext.accounts.party import get_party_account_currency
from erpnext.stock.get_item_details import get_item_details


class SubscriptionEnded(frappe.ValidationError):
	pass

class SubscriptionNotEnded(frappe.ValidationError):
	pass


class Subscription2(Document):
	def __init__(self, *args, **kwargs):
		"Override to get the invoice details before anything else"
		super(Subscription2, self).__init__(*args, **kwargs)
		self.invoice_document_type = "Sales Invoice" if self.party_type == "Customer" else "Purchase Invoice"

		self.latest_invoice = None
		invoice_names = frappe.db.get_all(self.invoice_document_type,
			filters={'subscription': self.name},
			order_by='to_date desc',
			page_length='1',
			pluck='name')
		if invoice_names:
			self.latest_invoice = invoice_names[0]

	### Override document methods
	def before_insert(self) -> None:
		self.update_subscription_period(self.start_date)
		if not self.cost_center:
			self.cost_center = get_default_cost_center(self.company)

	def after_insert(self) -> None:
		self.set_subscription_status()

	def update_subscription_period(self, start=None) -> None:
		self.next_invoice_start, self.next_invoice_end = self._get_subscription_period(start)

	def _get_subscription_period(self, start=None) -> tuple:
		start = self.get_current_invoice_start(start)
		return start, self.get_current_invoice_end(start)

	def get_current_invoice_start(self, start: datetime.date=None) -> datetime.date:
		""" Assumes:
		the subscription is inserted sending in the subscription start_date
		every time an invoice is generated invoice_end_date + 1 is sent in
		"""
		if self.is_new_subscription() and self.trial_period_end and self.trial_period_end > self.start_date:
			return add_days(self.trial_period_end, 1)
		elif start:
			return start
		else:
			return self.nowdate()

	def get_current_invoice_end(self, start: datetime.date) -> datetime.date:
		"""
		Anniversary or Calendar and after initial period: a billing period away from the start parameter
		Calendar and initial period: End of a calendar billing cycle
		"""
		start = getdate(start)
		# If calendar billing and we don't have a full month or year:
		if self.calendar_billing and (start.day != 1 or (self.billing_interval == 'Year' and start.month != 1)):
			billing_cycle_info = self.get_billing_cycle_data(self.billing_interval, self.billing_interval_count - 1)
			end = add_to_date(start, **billing_cycle_info)
			if self.billing_interval == 'Month':
				end = get_last_day(end)
			else:
				end = get_year_ending(end)
		else:
			billing_cycle_info = self.get_billing_cycle_data()
			end = add_to_date(start, **billing_cycle_info)

		if self.end_date and end > self.end_date:
			end = self.end_date

		return end

	def validate(self) -> None:
		self.validate_trial_period()
		self.validate_end_date()
		self.validate_calendar_billing()
		self.validate_prices()

	def validate_trial_period(self) -> None:
		"""
		Runs sanity checks on trial period dates for the `Subscription`
		"""
		if not self.trial_period_start and not self.trial_period_end:
			return
		elif self.trial_period_start and self.trial_period_end:
			if self.trial_period_end < self.trial_period_start:
				frappe.throw(_('Trial Period End Date cannot be before Trial Period Start Date'))
			if self.trial_period_start > self.start_date:
				frappe.throw(_('Trial Period Start Date cannot be after Subscription Start Date'))
		else:
			frappe.throw(_('Both Trial Period Start Date and Trial Period End Date must be set'))

	def validate_end_date(self) -> None:
		end_date = add_to_date(self.start_date, **self.get_billing_cycle_data())

		if self.end_date and self.end_date <= end_date:
			frappe.throw(_(f"End Date must be after at least one billing interval: > {end_date}"))

	def validate_calendar_billing(self) -> None:
		if not self.calendar_billing:
			return

		if self.billing_interval not in ('Month', 'Year'):
			frappe.throw(
				_("Billing Interval in Subscription Plan must be Month or Year for calendar billing")
			)

	def validate_prices(self) -> None:
		"Makes sure a price is available from the price list and sets the details in the item table"
		plan_doc = frappe.get_cached_doc('Subscription2 Plan', self.plan)
		currency = frappe.db.get_value('Price List', plan_doc.price_list, 'currency')
		invoice_date = self.next_invoice_end if self.billed_in_arrears else self.next_invoice_start
		pfactor = self.prorata_factor(self.next_invoice_start, self.next_invoice_end)
		self.price_list_currency = currency
		total = 0.0

		for sitem in self.items:
			details = self.get_plan_price(plan_doc, currency, invoice_date, sitem.item_code, sitem.qty)
			sitem.currency = currency
			if details['price_list_rate']:
				sitem.price_list_rate = details['price_list_rate']
				sitem.amount = sitem.qty * sitem.price_list_rate * pfactor * plan_doc.billing_interval_count
				total += sitem.amount
			else:
				msg = f'No price found for {frappe.bold(sitem.item_code)} in {frappe.get_desk_link("Price List", plan_doc.price_list)}'
				frappe.throw(_(msg))
		self.total = total

	def get_plan_price(self, plan_doc, currency, invoice_date, item_code, qty) -> dict:
		if plan_doc.price_determination == "Based On Price List":
			details = get_item_details(args={
				'transaction_date': invoice_date,
				'item_code': item_code,
				'qty': qty,
				'customer': self.party if self.party_type == 'Customer' else None,
				'supplier': self.party if self.party_type == 'Supplier' else None,
				'selling_price_list': plan_doc.price_list if self.party_type == 'Customer' else None,
				'buying_price_list': plan_doc.price_list if self.party_type == 'Supplier' else None,
				'doctype': self.invoice_document_type,
				'currency': currency,
				'company': self.company,
				'is_subcontracted': 0,
				'ignore_pricing_rule': 0,
			})
		return details

	def get_billing_cycle_data(self, interval=None, interval_count=None) -> Dict[str, int]:
		"""Returns a dict containing the billing cycle data"""
		data = {"days": -1}
		if interval is None:
			interval = self.billing_interval
		if interval_count is None:
			interval_count = self.billing_interval_count

		if interval == "Day":
			data["days"] += interval_count
		elif interval == "Week":
			data["days"] += interval_count * 7
		elif interval == "Month":
			data["months"] = interval_count
		elif interval == "Year":
			data["years"] = interval_count

		return data

	def get_billing_cycle_days(self) -> int:
		"The number of days in the whole billing cycle to work out the prorata factor"
		billing_cycle_info = self.get_billing_cycle_data()
		end = add_to_date(self.next_invoice_start, **billing_cycle_info)
		days = date_diff(end, self.next_invoice_start) + 1
		return days

	def is_new_subscription(self) -> bool:
		return not bool(self.latest_invoice)

	def is_trialling(self) -> bool:
		if not self.trial_period_start or not self.trial_period_end:
			return False

		return self.is_new_subscription() and self.nowdate() <= self.trial_period_end


	### Background Job Entry
	@frappe.whitelist()
	def process(self, now_date=None) -> None:
		"""Can supply a now parameter for testing"""
		self._nowdate = now_date
		if self.should_generate_invoice():
			self.create_invoice()

			if self.should_update_period():
				self.update_subscription_period(add_days(self.next_invoice_end, 1))

		if self.should_cancel_subscription():
			self.cancel_subscription()

		self.set_subscription_status()
		self.save()

	def nowdate(self) -> datetime.date:
		if not self.get('_nowdate'):
			self._nowdate = getdate(nowdate())
		return self._nowdate

	def is_finished(self) -> bool:
		if self.status in ('Completed', 'Cancelled'):
			return True
		return False

	def set_subscription_status(self) -> None:
		if self.is_finished():
			return

		if self.is_trialling():
			self.status = "Trialling"
		elif self.end_date and self.nowdate() > self.end_date:
			self.status = "Completed"
		elif self.overdue_invoice_count():
			self.status = "Overdue"
		elif self.unpaid_invoice_count():
			self.status = "Unpaid"
		else:
			self.status = "Active"

		self.save()

	def should_cancel_subscription(self) -> bool:
		""" Completed is not Cancelled!
		Conditions:
		not is_finished and
		cancel_at_period_end and
		  Arrears: now > next_invoice_end
		  Advance: now >= next_invoice_start
		Overdue invoice and cancel_if_overdue is set
		"""
		if self.is_finished():
			return False

		if self.cancel_at_period_end:
			if self.billed_in_arrears:
				if self.nowdate() > getdate(self.next_invoice_end):
					return True
			else:
				if self.nowdate() >= getdate(self.next_invoice_start):
					return True

		if self.cancel_if_overdue and self.overdue_invoice_count():
			return True

		return False

	def should_update_period(self) -> bool:
		""" Conditions:
		Not is_finished and
		Not past subscription end and
		cancel_at_period_end is not set
		"""
		if self.is_finished():
			return False

		if self.end_date and self.nowdate() > self.end_date:
			return False

		if self.cancel_at_period_end:
			return False

		return True

	def should_generate_invoice(self) -> bool:
		""" Conditions:
		not cancelled and
		not is_current_invoice_generated and
		not trialling and
		billed in arrears and now > next_invoice_end or
		billed in advance and
		  is new or
		  not marked for cancellation and now >= next_invoice_start
		"""
		if self.is_finished() or self.is_current_invoice_generated():
			return False

		if self.is_trialling():
			return False

		if self.billed_in_arrears:
			if self.nowdate() > getdate(self.next_invoice_end):
				return True
		else:
			if self.is_new_subscription():
				return True

			if not self.cancel_at_period_end and self.nowdate() >= getdate(self.next_invoice_start):
				return True
		return False

	def is_current_invoice_generated(self) -> bool:
		""" Conditions:
		Now is between the from and to dates of the latest invoice
		"""
		# Checks that there is a latest_invoice
		if self.is_new_subscription():
			return False

		invoice = frappe.get_doc(self.invoice_document_type, self.latest_invoice)
		# docstatus 2 == Cancelled
		if invoice.from_date <= self.nowdate() <= invoice.to_date and invoice.docstatus < 2:
			return True

		return False

	def create_invoice(self, from_date=None, to_date=None) -> Document:

		invoice = frappe.new_doc(self.invoice_document_type)
		plan_doc = frappe.get_doc('Subscription2 Plan', self.plan)

		# Subscription section
		invoice.subscription = self.name
		invoice.from_date = from_date or self.next_invoice_start
		invoice.to_date = to_date or self.next_invoice_end

		invoice.company = self.company
		invoice.set_posting_time = 1
		invoice.posting_date = invoice.to_date if self.billed_in_arrears else invoice.from_date

		if self.party_type == "Customer":
			invoice.customer = self.party
			invoice.selling_price_list = plan_doc.price_list
			tax_template = self.sales_tax_template
		else:
			invoice.supplier = self.party
			invoice.buying_price_list = plan_doc.price_list
			tax_template = self.purchase_tax_template
			if frappe.db.get_value('Supplier', self.party, 'tax_withholding_category'):
				invoice.apply_tds = 1

		invoice.currency = get_party_account_currency(self.party_type, self.party, self.company)
		invoice.cost_center = self.cost_center

		accounting_dimensions = get_accounting_dimensions()
		for dimension in accounting_dimensions:
			dim = self.get(dimension)
			if dim:
				invoice.update({
					dimension: dim
				})

		items_list = self.get_items(plan_doc, invoice.from_date, invoice.to_date)
		for item in items_list:
			invoice.append('items', item)

		if tax_template:
			invoice.taxes_and_charges = tax_template
			invoice.set_taxes()

		invoice.payment_terms_template = self.payment_terms_template

		# Discounts
		if self.additional_discount_percentage:
			invoice.additional_discount_percentage = self.additional_discount_percentage

		if self.additional_discount_amount:
			invoice.discount_amount = self.additional_discount_amount

		if self.additional_discount_percentage or self.additional_discount_amount:
			invoice.apply_discount_on = self.apply_additional_discount

		invoice.flags.ignore_mandatory = True
		invoice.set_missing_values()
		invoice.insert()

		if self.submit_invoice:
			invoice.submit()

		self.latest_invoice = invoice.name
		return invoice

	def prorata_factor(self, period_start: datetime.date, period_end: datetime.date) -> Union[int, float]:
		if self.prorata:
			length = date_diff(period_end, period_start) + 1
			return length / self.get_billing_cycle_days()
		else:
			return 1.0

	def get_items(self, plan_doc, from_date, to_date) -> List[Dict]:
		"""Gets the Invoice Items"""
		pfactor = self.prorata_factor(from_date, to_date)
		items = []
		dimensions = get_accounting_dimensions()
		for sitem in self.items:
			item = {
				"item_code": sitem.item_code,
				"qty": sitem.qty * pfactor * plan_doc.billing_interval_count,
				"rate": sitem.price_list_rate,
				"price_list_rate": sitem.price_list_rate,
				"currency": sitem.currency,
				"cost_center": self.cost_center,
			}

			if self.party == 'Customer':
				deferred_field = 'enable_deferred_revenue'
			else:
				deferred_field = 'enable_deferred_expense'

			deferred = frappe.db.get_value('Item', sitem.item_code, deferred_field)

			if deferred:
				item.update({
					deferred_field: deferred,
					'service_start_date': from_date,
					'service_end_date': to_date
				})

			for dimension in dimensions:
				dim = self.get(dimension)
				if dim:
					item.update({ dimension: dim })

			items.append(item)
		return items

	def overdue_invoice_count(self) -> int:
		return frappe.db.count(
			self.invoice_document_type,
			{
				"subscription": self.name,
				"status": ('like', 'Overdue%')
			}
		)

	def unpaid_invoice_count(self) -> int:
		return frappe.db.count(
			self.invoice_document_type,
			{
				"subscription": self.name,
				"status": ('like', 'Unpaid%')
			}
		)

	@frappe.whitelist()
	def cancel_subscription(self) -> None:
		"""
		This sets the subscription as cancelled. It will stop invoices from being generated
		but it will not affect already created invoices.
		"""
		if self.is_finished():
			frappe.throw(_("The subscription has already ended"), SubscriptionEnded)

		self.cancellation_date = self.nowdate()

		if self.status == "Active" and self.billed_in_arrears:
			self.create_invoice(self.next_invoice_start, self.cancellation_date)

		self.status = "Cancelled"
		self.save()

	@frappe.whitelist()
	def restart_subscription(self) -> None:
		if not self.is_finished():
			frappe.throw(_("The subscription has not ended"), SubscriptionNotEnded)

		self.status = "Active"
		self.cancellation_date = None
		if not self.is_current_invoice_generated():
			self.update_subscription_period(self.nowdate())
		self.save()

def process_all(now_date=None) -> None:
	"""Background update task"""
	# Optimisation to ignore all draft or  finished subscriptions
	for sname in frappe.get_all(
		"Subscription2",
		{"status": ("not in", ("Cancelled", "Completed"))},
		pluck="name"
	):
		try:
			subscription = frappe.get_doc("Subscription2", sname)
			subscription.process(now_date)
			frappe.db.commit()
		except Exception:
			frappe.log_error(frappe.get_traceback(), 'Subscription2 Error')
