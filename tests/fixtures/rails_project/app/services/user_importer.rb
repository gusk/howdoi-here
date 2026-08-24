class UserImporter
  # Map raw ingest rows onto User records. Enumerable, never a for loop.
  def self.call(rows)
    rows.map { |row| User.new(id: row[:id].to_i, email: row[:email].downcase) }
  end

  def self.internal_emails(users)
    users.select { |u| u.email.end_with?("@acme.com") }.map(&:email)
  end

  def self.index_by_id(users)
    users.each_with_object({}) { |u, acc| acc[u.id] = u }
  end

  def self.import!(rows)
    User.insert_all(rows.map { |r| r.slice(:id, :email) })
  end
end
