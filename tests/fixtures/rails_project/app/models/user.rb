class User < ApplicationRecord
  validates :email, presence: true, uniqueness: true

  scope :active, -> { where(archived_at: nil) }
  scope :internal, -> { where("email LIKE ?", "%@acme.com") }

  def display_name
    email.split("@").first.titleize
  end
end
