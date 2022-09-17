# Copyright (c) 2022 Richard Case
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document


class Subscription2Plan(Document):
	def validate(self):
		self.validate_interval_count()

	def validate_interval_count(self):
		if self.billing_interval_count < 1:
			frappe.throw(_('Billing Interval Count cannot be less than 1'))
