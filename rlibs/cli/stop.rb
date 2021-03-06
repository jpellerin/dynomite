options = {:erl_call => "erl_call"}

OptionParser.new do |opts|
  opts.banner = "Usage: dynomite stop [options]"

  contents =  File.read(File.dirname(__FILE__) + "/shared/common.rb")
  eval contents

  opts.separator ""
  opts.separator "Specific options:"
  opts.on("--erl_call [ERL_CALL]", "Path to erl_call command") do |erl_call|
    options[:erl_call] = "#{erl_call}/erl_call"
  end


end.parse!

cookie = Digest::MD5.hexdigest(options[:cluster] + "NomMxnLNUH8suehhFg2fkXQ4HVdL2ewXwM")

str = %Q(erl -sname console_#{$$} -hidden -setcookie #{cookie} -pa #{ROOT}/ebin/ -run commands start -run erlang halt -noshell -node #{options[:name]}@#{`hostname -s`.chomp} -m init -f stop)
puts str
exec str
