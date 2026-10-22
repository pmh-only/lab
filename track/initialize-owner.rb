# Use the pinned app's actual User lifecycle before its normal seeds. Never
# expose the upstream demo administrator or rewrite an existing owner's state.
Rails.logger.level = Logger::WARN
email = ENV.fetch('ADMIN_EMAIL').downcase
password = ENV.fetch('ADMIN_PASSWORD')
subject = ENV.fetch('OIDC_SUB')
raise 'Incomplete managed owner identity' unless email.include?('@') && password.length >= 48 && subject.length >= 16

created = false
User.transaction do
  User.connection.execute('SELECT pg_advisory_xact_lock(173879441)')
  owner = User.unscoped.find_by(provider: 'openid_connect', uid: subject)
  if owner.nil?
    raise 'Existing users require coordinated review; refusing owner takeover' unless User.unscoped.none?
    owner = User.create!(email: email, password: password, password_confirmation: password,
                         admin: true, status: :active, active_until: 100.years.from_now,
                         provider: 'openid_connect', uid: subject,
                         first_name: ENV.fetch('ADMIN_NAME').split.first)
    created = true
    raise 'Fresh native password verification failed' unless owner.valid_password?(password)
  end
  raise 'Existing native administrator identity differs' unless owner.admin? && owner.active?
end
raise 'Unexpected upstream demo administrator exists' if User.unscoped.exists?(email: 'demo@dawarich.app')
puts(created ? 'Fresh native owner created with verified IdP subject; no default demo account seeded' : 'Existing owner/password/identity preserved')
