#!/bin/sh
set -eu
bundle exec rails db:migrate
bundle exec rake data:migrate
bundle exec rails runner /bootstrap/initialize-owner.rb
# User now exists, so native seeds retain geography/tags without a demo account.
bundle exec rails db:seed
echo "Native migrations, administrator and geography seeds initialized"
