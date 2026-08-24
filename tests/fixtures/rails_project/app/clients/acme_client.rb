require "faraday"

class AcmeClient
  RETRIES = 3

  # Every outbound call goes through here. Upstream rate-limits hard.
  def self.connection
    Faraday.new(url: ENV.fetch("ACME_URL")) do |f|
      f.request :retry, max: RETRIES, backoff_factor: 2
      f.response :json
    end
  end

  def self.fetch_users
    connection.get("/users").body
  end
end
