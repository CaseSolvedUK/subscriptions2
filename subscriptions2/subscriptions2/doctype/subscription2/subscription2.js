// Copyright (c) 2022, Richard Case and contributors
// For license information, please see license.txt

frappe.ui.form.on('Subscription2', {
	setup: function (frm) {
		// Parent table queries
		frm.set_query('cost_center', function(doc, dt, dn) {
			return {
				filters: {
					company: frm.doc.company
				}
			};
		});
	},

	refresh: function (frm) {
		if (frm.is_new()) return;

		if (frm.doc.status !== 'Cancelled') {
			frm.add_custom_button(
				__('Fetch Subscription Updates'),
				() => frm.trigger('get_subscription_updates'),
				__('Actions')
			);

			frm.add_custom_button(
				__('Cancel Subscription'),
				() => frm.trigger('cancel_this_subscription'),
				__('Actions')
			);
		} else if (frm.doc.status === 'Cancelled') {
			frm.add_custom_button(
				__('Restart Subscription'),
				() => frm.trigger('renew_this_subscription'),
				__('Actions')
			);
		}
	},

	cancel_this_subscription: function (frm) {
		frappe.confirm(
			__('This action will stop future billing. Are you sure you want to cancel this subscription?'),
			() => {
				frm.call('cancel_subscription').then(r => {
					if (!r.exec) {
						frm.reload_doc();
					}
				});
			}
		);
	},

	renew_this_subscription: function (frm) {
		frappe.confirm(
			__('Are you sure you want to restart this subscription?'),
			() => {
				frm.call('restart_subscription').then(r => {
					if (!r.exec) {
						frm.reload_doc();
					}
				});
			}
		);
	},

	get_subscription_updates: function (frm) {
		frm.call('process').then(r => {
			if (!r.exec) {
				frm.reload_doc();
			}
		});
	},
});
