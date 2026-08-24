-- lead_crm — термінальна стадія: недооформлений лід пішов у CRM на прозвон
DROP INDEX IF EXISTS ux_orders_active;
CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_active ON orders(chat_id)
  WHERE stage NOT IN ('done', 'cancelled', 'returned', 'lead_crm');
