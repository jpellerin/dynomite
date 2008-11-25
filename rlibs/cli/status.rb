options = {}

OptionParser.new do |opts|
  opts.banner = "Usage: dynomite status [options]"

  contents =  File.read(File.dirname(__FILE__) + "/shared/common.rb")
  eval contents
end.parse!

cookie = Digest::MD5.hexdigest(options[:cluster] + "NomMxnLNUH8suehhFg2fkXQ4HVdL2ewXwM")

str = "erl_call \
  -sname #{options[:name]} \
  -c #{cookie} \
  -a 'membership nodes'"
exec str
