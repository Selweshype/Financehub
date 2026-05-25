<x-app-layout>
    <x-slot name="header">
        <div class="flex justify-between items-center">
            <h2 class="font-semibold text-xl text-gray-800 leading-tight">Accounts</h2>
            <a href="{{ route('accounts.create') }}"
               class="inline-flex items-center px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700">
                + Add Account
            </a>
        </div>
    </x-slot>

    <div class="py-8">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">

            @if (session('success'))
                <div class="mb-4 px-4 py-3 bg-green-100 text-green-800 rounded-md text-sm">{{ session('success') }}</div>
            @endif

            @if ($accounts->isEmpty())
                <div class="bg-white rounded-lg shadow p-12 text-center text-gray-500">
                    <p class="text-lg mb-2">No accounts yet.</p>
                    <a href="{{ route('accounts.create') }}" class="text-indigo-600 hover:underline">Add your first account</a>
                </div>
            @else
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                    @foreach ($accounts as $account)
                        <div class="bg-white rounded-lg shadow overflow-hidden">
                            <div class="h-2" style="background-color: {{ $account->color ?? '#6366F1' }}"></div>
                            <div class="p-6">
                                <div class="flex justify-between items-start mb-3">
                                    <div>
                                        <h3 class="font-semibold text-gray-900">{{ $account->name }}</h3>
                                        <span class="inline-block mt-1 px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs uppercase tracking-wide">
                                            {{ str_replace('_', ' ', $account->type) }}
                                        </span>
                                    </div>
                                    @unless($account->is_active)
                                        <span class="text-xs text-gray-400">Inactive</span>
                                    @endunless
                                </div>
                                <p class="text-2xl font-bold {{ $account->balance >= 0 ? 'text-gray-900' : 'text-red-600' }}">
                                    {{ $account->currency }} {{ number_format($account->balance, 2) }}
                                </p>
                                <div class="mt-4 flex gap-2">
                                    <a href="{{ route('accounts.edit', $account) }}"
                                       class="flex-1 text-center px-3 py-1.5 border border-gray-300 text-sm text-gray-700 rounded hover:bg-gray-50">
                                        Edit
                                    </a>
                                    <form action="{{ route('accounts.destroy', $account) }}" method="POST"
                                          onsubmit="return confirm('Delete this account and all its transactions?')">
                                        @csrf @method('DELETE')
                                        <button type="submit"
                                                class="px-3 py-1.5 border border-red-300 text-sm text-red-600 rounded hover:bg-red-50">
                                            Delete
                                        </button>
                                    </form>
                                </div>
                            </div>
                        </div>
                    @endforeach
                </div>
            @endif
        </div>
    </div>
</x-app-layout>
