// Prefill: save a form's values as a preset, apply a preset to a new or draft form.
// Plain Desk JS, no build step. Everything the server returns is escaped before it is shown.

frappe.provide("prefill");

$(document).on("form-refresh", (_event, frm) => {
	if (!prefill.is_available(frm)) return;

	frm.page.add_menu_item(__("Save as Preset"), () => prefill.open_save_dialog(frm));

	if (frm.doc.docstatus === 0) {
		// The presets themselves are loaded when this is clicked, not on every refresh.
		frm.add_custom_button(
			__("Apply a Preset"),
			() => prefill.open_chooser(frm),
			__("Presets")
		);
	}
});

Object.assign(prefill, {
	// New forms carry 0 for these, so a 0 does not count as "filled in".
	ZERO_IS_DEFAULT: ["Int", "Float", "Currency", "Percent", "Check"],

	is_available(frm) {
		const boot = frappe.boot.form_presets;
		const meta = frm.meta || {};
		return Boolean(
			boot &&
				boot.enabled &&
				!boot.excluded.includes(frm.doctype) &&
				!meta.issingle &&
				!meta.istable &&
				!meta.is_virtual
		);
	},

	escape(value) {
		return frappe.utils.escape_html(
			value === null || value === undefined ? "" : String(value)
		);
	},

	is_blank(value) {
		return value === null || value === undefined || value === "";
	},

	// Pre-ticked in the save dialog: values that are set. A 0 on a number or checkbox is a default, not a choice.
	has_value(df, value) {
		if (prefill.is_blank(value)) return false;
		return !(prefill.ZERO_IS_DEFAULT.includes(df.fieldtype) && flt(value) === 0);
	},

	// ---- Save as Preset ----

	async open_save_dialog(frm) {
		const { message: capturable } = await frappe.call({
			method: "prefill.api.get_capturable_fields",
			args: { doctype: frm.doctype },
		});

		const field_options = capturable.fields.map((df) => ({
			label: __(df.label),
			value: df.fieldname,
			checked: prefill.has_value(df, frm.doc[df.fieldname]),
		}));
		const table_options = capturable.tables.map((table) => ({
			label: __(table.label),
			value: table.fieldname,
			checked: (frm.doc[table.fieldname] || []).length > 0,
		}));

		const scopes = frappe.boot.form_presets.allow_everyone
			? "Private\nShared\nEveryone"
			: "Private\nShared";

		const fields = [
			{ fieldname: "title", fieldtype: "Data", label: __("Title"), reqd: 1 },
			{ fieldname: "description", fieldtype: "Small Text", label: __("Description") },
			{
				fieldname: "scope",
				fieldtype: "Select",
				label: __("Scope"),
				options: scopes,
				default: "Private",
			},
			{
				fieldname: "scope_warning",
				fieldtype: "HTML",
				options: `<p class="text-muted">${__(
					"Saved values are visible to everyone you share with."
				)}</p>`,
				depends_on: "eval:doc.scope!='Private'",
			},
			{
				fieldname: "shares",
				fieldtype: "Table",
				label: __("Share with"),
				depends_on: "eval:doc.scope=='Shared'",
				cannot_add_rows: false,
				in_place_edit: true,
				data: [],
				fields: [
					{
						fieldname: "share_type",
						fieldtype: "Select",
						label: __("Type"),
						options: "User\nRole",
						default: "User",
						in_list_view: 1,
						reqd: 1,
					},
					{
						fieldname: "user",
						fieldtype: "Link",
						options: "User",
						label: __("User"),
						in_list_view: 1,
					},
					{
						fieldname: "role",
						fieldtype: "Link",
						options: "Role",
						label: __("Role"),
						in_list_view: 1,
					},
					{
						fieldname: "can_edit",
						fieldtype: "Check",
						label: __("Can Edit"),
						in_list_view: 1,
					},
				],
			},
			{ fieldtype: "Section Break", label: __("Values to save") },
			{
				fieldname: "picked_fields",
				fieldtype: "MultiCheck",
				label: __("Fields"),
				options: field_options,
				columns: 2,
			},
		];

		if (table_options.length) {
			fields.push({
				fieldname: "picked_tables",
				fieldtype: "MultiCheck",
				label: __("Child tables"),
				options: table_options,
				columns: 2,
			});
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Save as Preset"),
			fields,
			size: "large",
			primary_action_label: __("Save"),
			primary_action: async (values) => {
				const saved = prefill.collect_values(
					frm,
					capturable,
					values.picked_fields || [],
					values.picked_tables || []
				);
				if (!Object.keys(saved.fields).length && !Object.keys(saved.tables).length) {
					frappe.msgprint(
						__("Tick at least one field or child table that has a value.")
					);
					return;
				}

				const shares = (values.shares || []).filter((row) => row.user || row.role);
				await frappe.call({
					method: "prefill.api.save_preset",
					args: {
						doctype: frm.doctype,
						title: values.title,
						description: values.description,
						scope: values.scope,
						shares: JSON.stringify(shares),
						values: JSON.stringify(saved),
					},
				});

				dialog.hide();
				frappe.show_alert({ message: __("Preset saved"), indicator: "green" });
			},
		});
		dialog.show();
	},

	// What goes into values_json. Blank values are left out, so a preset only carries what the user filled.
	collect_values(frm, capturable, picked_fields, picked_tables) {
		const saved = { version: 1, fields: {}, tables: {} };

		picked_fields.forEach((fieldname) => {
			const value = frm.doc[fieldname];
			if (!prefill.is_blank(value)) saved.fields[fieldname] = value;
		});

		capturable.tables
			.filter((table) => picked_tables.includes(table.fieldname))
			.forEach((table) => {
				const rows = (frm.doc[table.fieldname] || [])
					.map((row) => {
						const cells = {};
						table.fields.forEach((df) => {
							if (!prefill.is_blank(row[df.fieldname]))
								cells[df.fieldname] = row[df.fieldname];
						});
						return cells;
					})
					.filter((cells) => Object.keys(cells).length);
				if (rows.length) saved.tables[table.fieldname] = rows;
			});

		return saved;
	},

	// ---- Apply a preset ----

	async open_chooser(frm) {
		const { message: presets } = await frappe.call({
			method: "prefill.api.list_presets",
			args: { doctype: frm.doctype },
		});

		if (!presets || !presets.length) {
			frappe.msgprint(
				__(
					"There are no presets for {0} yet. Fill in a form, then use Menu > Save as Preset.",
					[__(frm.doctype)]
				)
			);
			return;
		}

		const dialog = new frappe.ui.Dialog({
			title: __("Apply a Preset"),
			fields: [{ fieldname: "list", fieldtype: "HTML" }],
		});

		const items = presets
			.map(
				(preset, index) => `
				<a class="list-group-item list-group-item-action" href="#" data-index="${index}">
					<div><b>${prefill.escape(preset.title)}</b>
						<span class="text-muted small"> ${prefill.escape(__(preset.scope))}</span></div>
					${
						preset.description
							? `<div class="text-muted small">${prefill.escape(
									preset.description
							  )}</div>`
							: ""
					}
					<div class="text-muted small">
						${prefill.escape(__("{0} values", [preset.field_count]))} &middot;
						${prefill.escape(__("used {0} times", [preset.use_count || 0]))}
					</div>
				</a>`
			)
			.join("");

		dialog.fields_dict.list.$wrapper
			.html(`<div class="list-group">${items}</div>`)
			.on("click", "[data-index]", (event) => {
				event.preventDefault();
				dialog.hide();
				prefill.open_diff(frm, presets[$(event.currentTarget).data("index")]);
			});

		dialog.show();
	},

	open_diff(frm, preset) {
		let result = null;
		// Select controls fire "change" while the dialog is still being built, before they have a value.
		let ready = false;
		const on_change = () => ready && load();

		const dialog = new frappe.ui.Dialog({
			title: __("Apply {0}", [preset.title]),
			size: "large",
			fields: [
				{
					fieldname: "mode",
					fieldtype: "Select",
					label: __("Fields"),
					default: "fill_empty",
					options: [
						{ label: __("Fill empty fields only"), value: "fill_empty" },
						{ label: __("Overwrite existing values"), value: "overwrite" },
					],
					change: on_change,
				},
				{
					fieldname: "table_mode",
					fieldtype: "Select",
					label: __("Child table rows"),
					default: "append",
					options: [
						{ label: __("Append rows"), value: "append" },
						{ label: __("Replace rows"), value: "replace" },
					],
					change: on_change,
				},
				{ fieldname: "diff", fieldtype: "HTML" },
			],
			primary_action_label: __("Apply"),
			primary_action: () => apply(),
		});

		const $diff = () => dialog.fields_dict.diff.$wrapper;

		const load = async () => {
			// The server decides what would change. The form is only sent so it can compare.
			({ message: result } = await frappe.call({
				method: "prefill.api.preview_apply",
				args: {
					preset: preset.name,
					doc: JSON.stringify(frm.doc),
					mode: dialog.get_value("mode") || "fill_empty",
					table_mode: dialog.get_value("table_mode") || "append",
				},
				freeze: true,
				freeze_message: __("Comparing"),
			}));
			$diff().html(prefill.render_diff(result));
		};

		const apply = async () => {
			const checked = (kind) =>
				$diff()
					.find(`input[data-kind="${kind}"]:checked`)
					.map((_i, input) => String($(input).data("key")))
					.get();

			const picked_fields = checked("field");
			const picked_rows = checked("row");
			if (!picked_fields.length && !picked_rows.length) {
				frappe.msgprint(__("Nothing is ticked."));
				return;
			}

			dialog.hide();

			for (const change of result.changes) {
				if (picked_fields.includes(change.fieldname)) {
					await frm.set_value(change.fieldname, change.new);
				}
			}

			result.tables.forEach((table) => {
				const rows = table.rows.filter((_row, index) =>
					picked_rows.includes(`${table.fieldname}:${index}`)
				);
				if (!rows.length) return;

				if (table.mode === "replace") frm.clear_table(table.fieldname);
				rows.forEach((row) => frm.add_child(table.fieldname, row.values));
				frm.refresh_field(table.fieldname);
			});

			frappe.call({ method: "prefill.api.record_use", args: { preset: preset.name } });
			frappe.show_alert({
				message: __("Preset applied. Review the form, then save."),
				indicator: "green",
			});
		};

		dialog.show();
		load().then(() => (ready = true));
	},

	short(value) {
		if (prefill.is_blank(value)) return `<span class="text-muted">${__("empty")}</span>`;
		return prefill.escape(frappe.ellipsis(String(value), 80));
	},

	render_diff(result) {
		const rows = [];

		result.changes.forEach((change) => {
			const skipped = change.action === "skip";
			rows.push(`
				<tr class="${skipped ? "text-muted" : ""}">
					<td><input type="checkbox" data-kind="field" data-key="${prefill.escape(change.fieldname)}"
						${skipped ? "disabled" : "checked"}></td>
					<td>${prefill.escape(__(change.label))}</td>
					<td>${prefill.short(change.current)}</td>
					<td>${skipped ? "" : prefill.short(change.new)}</td>
					<td class="small">${skipped ? prefill.escape(change.reason) : ""}</td>
				</tr>`);
		});

		result.tables.forEach((table) => {
			const label = prefill.escape(__(table.label));
			if (table.action === "skip") {
				rows.push(`
					<tr class="text-muted">
						<td><input type="checkbox" disabled></td>
						<td colspan="3">${label}</td>
						<td class="small">${prefill.escape(table.reason)}</td>
					</tr>`);
				return;
			}

			table.rows.forEach((row, index) => {
				const cells = Object.entries(row.values)
					.map(([key, value]) => `${prefill.escape(key)}: ${prefill.short(value)}`)
					.join(", ");
				const skipped = row.skipped
					.map(
						(cell) => `${prefill.escape(cell.label)} (${prefill.escape(cell.reason)})`
					)
					.join(", ");
				rows.push(`
					<tr>
						<td><input type="checkbox" data-kind="row" data-key="${prefill.escape(
							table.fieldname
						)}:${index}" checked></td>
						<td>${label} ${__("row {0}", [index + 1])}</td>
						<td class="text-muted">${
							table.mode === "replace"
								? __("replaces {0} existing rows", [table.current_rows])
								: __("added after {0} existing rows", [table.current_rows])
						}</td>
						<td>${cells}</td>
						<td class="small text-muted">${skipped ? __("Skipped: {0}", [skipped]) : ""}</td>
					</tr>`);
			});
		});

		const warnings = result.warnings
			.map((warning) => `<p class="text-muted small">${prefill.escape(warning)}</p>`)
			.join("");

		if (!rows.length)
			return `<p class="text-muted">${__("This preset has nothing to apply.")}</p>`;

		return `
			<table class="table table-bordered table-sm">
				<thead><tr>
					<th style="width: 2rem"></th><th>${__("Field")}</th><th>${__("Now")}</th>
					<th>${__("Preset")}</th><th>${__("Note")}</th>
				</tr></thead>
				<tbody>${rows.join("")}</tbody>
			</table>${warnings}`;
	},
});
