
from frappe import _


def get_data():
	return {
		'fieldname': 'subscription2_plan',
		'non_standard_fieldnames': {
			'Payment Request': 'plan',
			'Subscription2': 'plan'
		},
		'transactions': [
			{
				'label': _('References'),
				'items': ['Payment Request', 'Subscription2']
			}
		]
	}
