frappe.listview_settings['Subscription2'] = {
	get_indicator: function(doc) {
		if(doc.status === 'Trialling') {
			return [__("Trialling"), "yellow", "status,=,Trialling"];
		} else if(doc.status === 'Active') {
			return [__("Active"), "green", "status,=,Active"];
		} else if(doc.status === 'Completed') {
			return [__("Completed"), "green", "status,=,Completed"];
		} else if(doc.status === 'Overdue') {
			return [__("Overdue"), "red", "status,=,Overdue"];
		} else if(doc.status === 'Unpaid') {
			return [__("Unpaid"), "orange", "status,=,Unpaid"];
		} else if(doc.status === 'Cancelled') {
			return [__("Cancelled"), "gray", "status,=,Cancelled"];
		}
	}
};
